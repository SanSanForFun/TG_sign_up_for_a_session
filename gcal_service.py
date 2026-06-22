import os
import logging
import uuid
import asyncio
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError


class GoogleCalendarService:
    def __init__(self, creds_path: str, calendar_id: str, tz_key: str, enabled: bool = False):
        self.enabled = enabled and bool(calendar_id)
        self.calendar_id = calendar_id
        self.tz_key = tz_key
        self.service = None
        if self.enabled:
            self._init_credentials(creds_path)

    def _init_credentials(self, creds_path: str):
        if not os.path.exists(creds_path):
            logging.warning(f"⚠️ Файл {creds_path} не найден. GCal отключен.")
            self.enabled = False
            return
        try:
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=["https://www.googleapis.com/auth/calendar"]
            )
            self.service = build("calendar", "v3", credentials=creds)
            logging.info("📅 Google Calendar service initialized.")
        except Exception as e:
            logging.error(f"❌ GCal init failed: {e}")
            self.enabled = False

    def _create_sync(self, summary, start_dt, end_dt, desc):
        if not self.enabled or not self.service:
            return None, None
        try:
            req_id = f"req-{uuid.uuid4().hex[:8]}"
            event = {
                "summary": summary,
                "description": desc,
                "start": {"dateTime": start_dt.isoformat(), "timeZone": self.tz_key},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": self.tz_key},
                "conferenceData": {
                    "createRequest": {"requestId": req_id, "conferenceSolutionKey": {"type": "hangoutsMeet"}}
                }
            }
            result = self.service.events().insert(
                calendarId=self.calendar_id, body=event, conferenceDataVersion=1
            ).execute()
            return result.get("id"), result.get("hangoutLink")
        except HttpError as e:
            status = e.resp.status if hasattr(e, 'resp') else 0
            if status == 401:
                logging.critical("🔑 GCal Token revoked/expired. Отключите и пересоздайте Service Account.")
                self.enabled = False
            elif status == 429:
                logging.warning("⏳ GCal Quota exceeded. Повторите позже.")
            else:
                logging.error(f"❌ GCal API error {status}: {e}")
            return None, None
        except RefreshError as e:
            logging.error(f"❌ GCal Refresh error: {e}")
            self.enabled = False
            return None, None

    def _delete_sync(self, event_id):
        if not self.enabled or not self.service or not event_id:
            return
        try:
            self.service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
        except HttpError as e:
            logging.error(f"❌ GCal delete error: {e}")

    async def create_event(self, summary, start_dt, end_dt, desc):
        return await asyncio.to_thread(self._create_sync, summary, start_dt, end_dt, desc)

    async def delete_event(self, event_id: str):
        return await asyncio.to_thread(self._delete_sync, event_id)
