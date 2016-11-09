from mock import ANY, call, MagicMock, patch, PropertyMock
import unittest

import fedimg
from fedimg.services.gce import (
    GCEService,
    ContainerDoesNotExistError,
    ImageURLError,
    SSHConnectionError
)


def create_mock(name=None, **kwargs):
    """
    Creates a MagicMock object with the ability to set predefined Mock
    attributes (such as name).
    """
    mockobj = MagicMock(**kwargs)
    if name:
        type(mockobj).name = PropertyMock(return_value=name)
    return mockobj


class TestGCEService(unittest.TestCase):

    FAKE_IMAGE_FILE_NAME = 'fake-img-1.2-3.tar.gz'
    FAKE_IMAGE_URL = 'http://fake.fedimg.com/' + FAKE_IMAGE_FILE_NAME

    @patch('fedimg.services.gce.get_compute_driver')
    @patch('fedimg.services.gce.get_storage_driver')
    def setUp(self, get_storage_driver, get_compute_driver):
        storage = MagicMock()
        compute = MagicMock()
        get_storage_driver.return_value = storage
        get_compute_driver.return_value = compute
        self.svc = GCEService()
        self.mock_storage = storage.return_value
        self.mock_compute = compute.return_value

    @patch('fedimg.services.gce.GCEService.cleanup')
    def test_context_manager(self, cleanup):
        """
        Test the service can be used as a context manager and cleanup is
        called at the end.
        """
        with self.svc:
            pass
        cleanup.assert_called_with()
        self.assertEquals(cleanup.call_count, 1)

    def test_cleanup(self):
        """
        Test the cleanup method deletes all resources and forgets them.
        """
        image1 = create_mock(name='gce-image-1')
        image2 = create_mock(name='gce-image-2')
        self.svc.gce_images.extend((image1, image2))

        node1 = create_mock(name='node-1')
        node2 = create_mock(name='node-2')
        self.svc.nodes.extend((node1, node2))

        self.svc.cleanup()

        self.mock_compute.destroy_node.assert_has_calls((
            call(node1, destroy_boot_disk=True),
            call(node2, destroy_boot_disk=True),
        ), any_order=True)
        self.assertEquals(self.mock_compute.destroy_node.call_count, 2)

        image1.delete.assert_called_once_with()
        image2.delete.assert_called_once_with()

        self.assertEquals(len(self.svc.nodes), 0)
        self.assertEquals(len(self.svc.gce_images), 0)

    @patch('fedimg.services.gce.requests')
    def test_upload_creates_container(self, requests):
        """
        Test the upload method creates the container if it doesn't exist.
        """
        container = fedimg.GCE_STORAGE_CONTAINER
        requests.get.return_value.ok = True
        self.mock_storage.get_container.side_effect = \
            ContainerDoesNotExistError(None, None, None)
        self.svc.upload(self.FAKE_IMAGE_URL)
        self.mock_storage.get_container.assert_called_once_with(container)
        self.mock_storage.create_container.assert_called_once_with(container)

    @patch('fedimg.services.gce.requests')
    def test_upload_reuses_container(self, requests):
        """
        Test the upload method reuses the container if it already exists.
        """
        container = fedimg.GCE_STORAGE_CONTAINER
        requests.get.return_value.ok = True
        self.svc.upload(self.FAKE_IMAGE_URL)
        self.mock_storage.get_container.assert_called_once_with(container)
        self.mock_storage.create_container.assert_not_called()

    def test_upload_bad_url(self):
        """
        Test the upload method raises an error with an unresolvable image URL.
        """
        with self.assertRaises(ImageURLError):
            self.svc.upload(self.FAKE_IMAGE_URL)

    @patch('fedimg.services.gce.requests')
    def test_upload_bad_url_response(self, requests):
        """
        Test the upload method raises an error with the response code included
        when it is not 200 OK.
        """
        requests.get.return_value.ok = False
        requests.get.return_value.status_code = -1
        with self.assertRaisesRegexp(ImageURLError, '.*response code was -1.'):
            self.svc.upload(self.FAKE_IMAGE_URL)

    @patch('fedimg.services.gce.ssh_connection_works')
    def test_verify_resources_stored(self, ssh_conn):
        """
        Test the verify method stores the cloud resources it creates.
        """
        image = create_mock(name=self.FAKE_IMAGE_FILE_NAME)
        self.svc.verify(image)
        self.assertEquals(len(self.svc.nodes), 1)
        self.assertEquals(len(self.svc.gce_images), 1)

    @patch('fedimg.services.gce.ssh_connection_works')
    def test_verify_image_renamed(self, ssh_conn):
        """
        Test the verify method renames the GCE image to only alphanumeric and
        hyphen characters.
        """
        image = create_mock(name=self.FAKE_IMAGE_FILE_NAME)
        self.svc.verify(image)
        self.mock_compute.ex_create_image.assert_called_with(
                'fake-img-1-2-3', ANY, wait_for_completion=True)

    @patch('fedimg.services.gce.ssh_connection_works')
    def test_verify_cheapest_size(self, ssh_conn):
        """
        Test the verify method uses the cheapest instance size.
        """
        sizes = [create_mock(price=p) for p in (1.2, .1, 999, .011)]
        cheapest = create_mock(price=.01)
        sizes.insert(3, cheapest)

        self.mock_compute.list_sizes.return_value = sizes
        image = create_mock(name=self.FAKE_IMAGE_FILE_NAME)
        self.svc.verify(image)
        self.mock_compute.create_node.assert_called_with(
                ANY, cheapest, ANY, location=ANY)

    @patch('fedimg.services.gce.ssh_connection_works')
    def test_verify_failed_ssh_connection(self, ssh_conn):
        """
        Test the verify method raises an error if the SSH connection fails.
        """
        ssh_conn.return_value = False
        image = create_mock(name=self.FAKE_IMAGE_FILE_NAME)
        with self.assertRaises(SSHConnectionError):
            self.svc.verify(image)

if __name__ == '__main__':
    unittest.main()
