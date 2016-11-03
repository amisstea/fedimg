# This file is part of fedimg.
# Copyright (C) 2014 Red Hat, Inc.
#
# fedimg is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# fedimg is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with fedimg; if not, see http://www.gnu.org/licenses,
# or write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#
# Authors:  David Gay <dgay@redhat.com>
#           Alex Misstear <amisstea@redhat.com>
#

import logging
import os
import re
import requests
import time

from libcloud.compute.providers import get_driver as get_compute_driver
from libcloud.storage.providers import get_driver as get_storage_driver
from libcloud.common.google import ResourceNotFoundError
from libcloud.compute.types import Provider as ComputeProvider
from libcloud.storage.types import (
    Provider as StorageProvider,
    ContainerDoesNotExistError
)

import fedimg
from fedimg.util import ssh_connection_works
from fedimg.common import BaseService, ImageURLError, SSHConnectionError

log = logging.getLogger(__name__)


class GCEService(BaseService):

    # Base URL for storage objects. Used to point to an object during image
    # creation.
    STORAGE_URL = 'https://storage.googleapis.com'

    # 4MB Chunk size for transferring image
    CHUNK_SIZE =  4 * 1024 * 1024

    def __init__(self):
        super(GCEService, self).__init__()

        # Compute images. Only used for test the image object.
        self.gce_images = []

        # Compute instance. Only used to test the image object.
        self.nodes = []

        Storage = get_storage_driver(StorageProvider.GOOGLE_STORAGE)
        self.storage = Storage(key=fedimg.GCE_EMAIL,
                               secret=fedimg.GCE_KEYPATH,
                               project=fedimg.GCE_PROJECT_ID)

        Compute = get_compute_driver(ComputeProvider.GCE)
        self.compute = Compute(fedimg.GCE_EMAIL,
                               key=fedimg.GCE_KEYPATH,
                               project=fedimg.GCE_PROJECT_ID)

    def cleanup(self):
        # Delete the test instances
        for node in self.nodes:
            log.info('Deleting test instance: {0}'.format(node.name))
            try:
                if not self.compute.destroy_node(node, destroy_boot_disk=True):
                    log.warning('Failed to delete test instance')
            except ResourceNotFoundError:
                log.debug('No test instance to delete')

        # Delete the test images
        for gce_image in self.gce_images:
            log.info('Deleting test image: {0}'.format(gce_image.name))
            try:
                if not gce_image.delete():
                    log.warning('Failed to delete test image')
            except ResourceNotFoundError:
                log.debug('No test image to delete')

    def upload(self, image_url, compose_meta=None):
        object_name = os.path.basename(image_url)
        container_name = fedimg.GCE_STORAGE_CONTAINER

        log.info('Uploading {0} to container {1}'.format(image_url,
                                                         container_name))

        # Get or create the container
        try:
            container = self.storage.get_container(container_name)
        except ContainerDoesNotExistError:
            log.info('Creating container: {0}'.format(container_name))
            container = self.storage.create_container(container_name)

        # Open a stream to the image URL
        resp = requests.get(image_url, stream=True)
        if not resp.ok:
            raise ImageURLError('GET request to image failed ({0}). '
                                'The server response code was {1}'
                                .format(image_url, resp.status_code))

        # Transfer via a stream to avoid the need for local storage
        iterator = resp.iter_content(chunk_size=self.CHUNK_SIZE)
        return self.storage.upload_object_via_stream(
                iterator, container, object_name)

    def test(self, image):
        log.info('Testing image {0}'.format(image.name))

        # GCE image names can only contain alphanumerics and hyphens. Replace
        # all other characters with hyphens.
        gce_image_name = re.sub('[^a-zA-Z\d]+', '-',
                                image.name.split('.tar.gz')[0])

        image_url = '{0}/{1}/{2}'.format(self.STORAGE_URL,
                                         fedimg.GCE_STORAGE_CONTAINER,
                                         image.name)

        # Create a GCE image
        log.info('Creating GCE image "{name}" from image object "{url}"...'
                 .format(name=gce_image_name, url=image_url))
        gce_image = self.compute.ex_create_image(gce_image_name,
                                                 image_url,
                                                 wait_for_completion=True)
        self.gce_images.append(gce_image)

        # Any location will do for the test instance
        location = self.compute.list_locations()[0]

        # Use the instance size which will impose the least cost
        sizes = self.compute.list_sizes(location=location)
        sizes.sort(key=lambda x: x.price)
        size = sizes[0]

        # Launch an instance (node) from the GCE image
        log.info('Launching test instance {0}'.format(gce_image.name))
        node = self.compute.create_node(gce_image.name,
                                        size,
                                        gce_image,
                                        location=location)
        self.nodes.append(node)

        # Wait up to 10 mins for the instance to be running
        log.info('Waiting until instance {0} is running...'.format(node.name))
        self.compute.wait_until_running((node,),
                                        wait_period=10,
                                        timeout=600)
        log.info('Instance {0} is now running'.format(node.name))

        # Try to SSH into the instance
        log.info('Testing SSH connectivity to the instance...')
        if not ssh_connection_works(fedimg.GCE_EMAIL.split('@')[0],
                                    node.public_ips[0],
                                    fedimg.GCE_KEYPATH,
                                    attempts=60,
                                    interval=60):
            raise SSHConnectionError('Cannot SSH to test instance {0}. '
                                     'Perhaps the image is improperly '
                                     'configured for GCE.'
                                     .format(node.name))
        log.info('Image {0} passed a basic sanity test'.format(image.name))

    def share(self, image, entities):
        for entity in entities:
            log.info('Sharing image {0} with {1}'.format(image.name, entity))
            self.storage.ex_set_permissions(fedimg.GCE_STORAGE_CONTAINER,
                                            object_name=image.name,
                                            entity=entity,
                                            role='READER')

    def publish(self, image):
        log.info('Publishing image {0} publicly'.format(image.name))
        self.storage.ex_set_permissions(fedimg.GCE_STORAGE_CONTAINER,
                                        object_name=image.name,
                                        entity='allUsers',
                                        role='READER')
