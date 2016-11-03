# This file is part of fedimg.
# Copyright (C) 2016 Red Hat, Inc.
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
# Authors:  Alex Misstear <amisstea@redhat.com>
#

import logging

log = logging.getLogger(__name__)


class ServiceError(Exception):
    """
    Generic cloud service related error.
    """
    pass


class ImageURLError(ServiceError):
    """
    Raised when there are issues accessing the URL to an image.
    """
    pass


class SSHConnectionError(ServiceError):
    """
    Raised when an SSH connection fails to a resource.
    """
    pass


class BaseService(object):
    
    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        self.cleanup()

    def cleanup(self):
        """
        A hook for procedures which should be done after any other calls.
        Called automatically when this class is used as a context manager.
        """
        pass

    def upload(self, image_url):
        """
        Uploads the image from the source URL and into the cloud service.
        """
        raise NotImplementedError('upload() has not been implemented')

    def test(self, image):
        """
        Performs a sanity level test of the image in the cloud service.
        """
        raise NotImplementedError('test() has not been implemented')

    def share(self, image, entities):
        """
        Distributes the image to a narrow audience. Intented for handing the
        image off to groups/individuals for further testing.
        """
        raise NotImplementedError('share() has not been implemented')

    def publish(self, image):
        """
        Releases the image to the public.
        """
        raise NotImplementedError('publish() has not been implemented')
