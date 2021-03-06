#!/usr/local/bin/python3.6

import os
import time
import tarfile
import logging
from io import BytesIO, TextIOWrapper
from tempfile import SpooledTemporaryFile

import apiclient
from google.oauth2 import service_account

from django.core.management.base import BaseCommand
from django.core.management import call_command

SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'folkrnn-gdrive.json'

logger = logging.getLogger(__name__)

def backup_suffix():
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    server = 'production' if 'FOLKRNN_PRODUCTION' in os.environ else 'dev'
    return f'_backup_{server}_{timestamp}'

class Command(BaseCommand):
    """"
    Backup management using Google Drive. A Django management command.
    i.e `python3.6 /vagrant/folk_rnn_webapp/folk_rnn_site/manage.py backup`
    
    Note: the Google accreditation is not user authorised, so these files will not be visible to the user in Google Drive.
    https://developers.google.com/api-client-library/python/auth/service-accounts

    Includes utility functions, typically for interactive use, i.e.
        cd /folk_rnn_webapp/folk_rnn_site
        python3.6
        from backup.management.commands.backup import Command
        backup = Command()
        backup.list_stored_files()
    """
    help = 'Archives folkrnn and machinefolksession data in Google Drive'
    
    def __init__(self):
        # Establish Google Drive client
        credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        self.drive = apiclient.discovery.build('drive', 'v3', credentials=credentials)
    
    def handle(self, *args, **kwargs):
        '''
        Process the command (i.e. the django manage.py entrypoint)
        '''
        logger.info('Backup starting.')
        
        logger.info('Backing up tunes...')
        self.archive_store_folder('/var/opt/folk_rnn_task/tunes')
        logger.info('Backing up logs...')
        self.archive_store_folder('/var/log/folk_rnn_webapp/')
        logger.info('Backing up database...')
        self.archive_store_database()
        
        logger.info("Backup completed.")
    
    def archive_store_database(self):
        """
        Archive and store in Google Drive the contents of the folder (recursively)
        Returns name of uploaded file
        """
        data = BytesIO()
        # contenttypes and auth.Permission are auto-regenerated and not to be trusted across database instances
        # e.g. https://stackoverflow.com/questions/853796/problems-with-contenttypes-when-loading-a-fixture-in-django
        call_command(
                'dumpdata', 
                all=True, 
                format='json', 
                indent=4, 
                use_natural_foreign_keys=True,
                exclude=('contenttypes', 'auth.Permission'), 
                stdout=TextIOWrapper(data, write_through=True),
                )
        with SpooledTemporaryFile() as f:
            # Archive to tar
            with tarfile.open(fileobj=f, mode='x:bz2') as tar:
                info = tarfile.TarInfo('db_data.json')
                info.size = data.tell()
                data.seek(0)
                tar.addfile(info, data)
            data.close()
            # Store in Google Drive
            body = {
                'name': 'db_data' + backup_suffix() + '.tar.gz',
                }
            media_body = apiclient.http.MediaIoBaseUpload(f, 
                                            mimetype='application/gzip', 
                                            resumable=True,
                                            )
            request = self.drive.files().create(
                                body=body,
                                media_body=media_body,
                                )
            try: 
                response = None
                while response is None:
                    status, response = request.next_chunk()
            except apiclient.errors.HttpError as e:
              if e.resp.status in [404]:
                logger.error(f'archive_store_folder: 404, {e}') # It should... # Start the upload all over again.
              elif e.resp.status in [500, 502, 503, 504]:
                logger.error(f'archive_store_folder: 5xx, {e}') # It should... # Call next_chunk() again, but use an exponential backoff for repeated errors.
              else:
                logger.error(f'archive_store_folder: {e}') # It should... # Do not retry. Log the error and fail.
        return body['name']
        
    def archive_store_database_media(self):
        # TODO: if apps end up having imagefields, filefields etc.
        # See e.g.
        # https://github.com/nathan-osman/django-archive/blob/master/django_archive/management/commands/archive.py
        print('Not implemented. No database media yet!')
        pass
    
    def archive_store_folder(self, folder_path):
        """
        Archive and store in Google Drive the contents of the folder (recursively)
        Returns name of uploaded file
        """
        folder_path = os.path.normpath(folder_path)
        folder_name = os.path.basename(folder_path)
        with SpooledTemporaryFile() as f:
            # Archive to tar
            with tarfile.open(fileobj=f, mode='x:bz2') as tar:
                tar.add(folder_path)
            # Store in Google Drive
            body = {
                'name': folder_name + backup_suffix() + '.tar.gz',
                }
            media_body = apiclient.http.MediaIoBaseUpload(f, 
                                            mimetype='application/gzip', 
                                            resumable=True,
                                            )
            request = self.drive.files().create(
                                body=body,
                                media_body=media_body,
                                )
            try: 
                response = None
                while response is None:
                    status, response = request.next_chunk()
            except apiclient.errors.HttpError as e:
              if e.resp.status in [404]:
                logger.error(f'archive_store_folder: 404, {e}') # It should... # Start the upload all over again.
              elif e.resp.status in [500, 502, 503, 504]:
                logger.error(f'archive_store_folder: 5xx, {e}') # It should... # Call next_chunk() again, but use an exponential backoff for repeated errors.
              else:
                logger.error(f'archive_store_folder: {e}') # It should... # Do not retry. Log the error and fail.
        return body['name']

    def _list_stored_files(self):
        next_page_token = 'no token for first page'
        while next_page_token is not None:
            kwargs = {'orderBy':'createdTime desc'}
            if next_page_token and next_page_token != 'no token for first page':
                kwargs['pageToken'] = next_page_token
            drive_list = self.drive.files().list(**kwargs).execute()
            if 'nextPageToken' in drive_list:
                next_page_token = drive_list['nextPageToken']
            else:
                next_page_token = None
            for meta in drive_list['files']:
                yield self.drive.files().get(fileId=meta['id'], fields='id, name,size,createdTime').execute()

    def list_stored_files(self):
        """
        Utility function, typically for interactive use
        """
        print('Listing all stored files')
        for file_info in self._list_stored_files():
            print(f"{file_info['name']:60}{file_info['size']:10}{file_info['createdTime']}")
    
    def download_file(self, file_id, file_path):
        """
        Utility function, typically for interactive use
        """
        request = self.drive.files().get_media(fileId=file_id)
        with open(file_path, 'wb') as f:
            downloader = apiclient.http.MediaIoBaseDownload(f, request)
            try:
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                print(f'Downloaded {file_path}')
            except apiclient.errors.HttpError as e:
              if e.resp.status in [404]:
                print('Error: 404') # It should... # Start the upload all over again.
              elif e.resp.status in [500, 502, 503, 504]:
                print('Error: 5xx') # It should... # Call next_chunk() again, but use an exponential backoff for repeated errors.
              else:
                print('Error') # It should... # Do not retry. Log the error and fail.
    
    def download_file_named(self, filename):
        """
        Utility function, typically for interactive use
        """
        query = f"name='{filename}'"
        drive_list = self.drive.files().list(q=query).execute()
        try:
           file_id = drive_list['files'][0]['id']
        except:
            print(f'Could not find {filename}')
            raise ValueError
        self.download_file(file_id, filename)
    
    def download_latest_production_backup(self, to_dir=''):
        names = [
            ['db_data_backup_production_', None, None],
            ['folk_rnn_webapp_backup_production_', None, None],
            ['tunes_backup_production_', None, None],
            ]
            
        # relies on _list_stored_files's newest-first ordering request
        for file_info in self._list_stored_files():
            for name in names:
                if file_info.get('name').startswith(name[0]):
                    name[1] = file_info.get('id')
                    name[2] = file_info.get('name')
            if all(x[1] for x in names):
                for name in names:
                    download_path = os.path.join(to_dir, name[2])
                    self.download_file(name[1], download_path)
                    name.append(download_path)
                break
        return ([x[3] for x in names])
                    
    def delete_file(self, file_id):
        """
        Utility function, typically for interactive use
        """
        self.drive.files().delete(fileId=file_id).execute()
    
    def delete_file_named(self, filename):
        """
        Utility function, typically for interactive use
        """
        query = f"name='{filename}'"
        drive_list = self.drive.files().list(q=query).execute()
        try:
           file_id = drive_list['files'][0]['id']
        except:
            print('Could not find {filename}')
            raise ValueError
        print(f"Deleting {drive_list['files'][0]['name']}")
        self.delete_file(file_id)
        
    def delete_all(self):
        """
        Utility function, typically for interactive use
        """
        drive_list = self.drive.files().list().execute()
        for meta in drive_list['files']:
            print(f"Deleting {meta['name']}...")
            self.drive.files().delete(fileId=meta['id']).execute()

if __name__ == '__main__':
    backup = Command()
    backup.list_stored_files()
