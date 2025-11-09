from __future__ import print_function
import pathlib
import pickle
import os.path
from mimetypes import MimeTypes
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.http import MediaFileUpload
import logging

class DriveAPI:
    global SCOPES
    
    # Define the scopes
    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self):
        self.creds = None
        # Check if file token.pickle exists
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                self.creds = pickle.load(token)
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'common/credentials.json', SCOPES)
                self.creds = flow.run_local_server(port=0)
            with open('token.pickle', 'wb') as token:
                pickle.dump(self.creds, token)

        # Connect to the API service
        self.service = build('drive', 'v3', credentials=self.creds)

        # # request a list of first N files or
        # # folders with name and id from the API.
        # results = self.service.files().list(
        #     pageSize=100, fields="files(id, name)").execute()
        # items = results.get('files', [])

        # # print a list of files

        # print("Here's a list of files: \n")
        # print(*items, sep="\n", end="\n\n")

    def FileUpload(self, filepath):
      
        # Extract the file name out of the file path
        name = filepath.split('/')[-1]
        
        # Find the MimeType of the file
        mimetype = MimeTypes().guess_type(name)[0]
        
        # create file metadata
        file_metadata = {'name': name}

        try:
            media = MediaFileUpload(filepath, mimetype=mimetype)
            
            # Create a new file in the Drive storage
            file = self.service.files().create(
                body=file_metadata, media_body=media, fields='id').execute()
            
            logging.info("File Uploaded.")
        
        except:
            
            # Raise UploadError if file is not uploaded.
            logging.error("Can't Upload File.")

obj = DriveAPI()
root_path = (pathlib.Path().absolute())
obj.FileUpload(str(root_path) + "/futures_exchange_info.json") #TODO to edit to include real file names.