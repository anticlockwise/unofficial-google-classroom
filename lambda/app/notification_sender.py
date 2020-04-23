from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


if __name__ == '__main__':
    service = build('classroom', 'v1', credentials=creds)