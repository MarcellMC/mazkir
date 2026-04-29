"""Google Calendar integration service for Mazkir."""
import logging
import socket
from datetime import date as date_type, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import httplib2
import google_auth_httplib2
import pytz

# Force IPv4 for Google API connections (IPv6 times out on some networks)
_original_getaddrinfo = socket.getaddrinfo

def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Override getaddrinfo to force IPv4 for googleapis.com"""
    if 'googleapis.com' in str(host):
        family = socket.AF_INET
    return _original_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = _ipv4_only_getaddrinfo
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Scopes required for calendar access
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Color IDs for Google Calendar
COLOR_GREEN = '10'  # Completed events
COLOR_DEFAULT = None  # Use calendar default


class CalendarService:
    """Service for Google Calendar integration."""

    def __init__(
        self,
        credentials_path: Path,
        token_path: Path,
        timezone: str = "Asia/Jerusalem",
        default_habit_time: str = "07:00",
        default_event_duration: int = 30,
        calendar_id: Optional[str] = None,
        calendar_include: Optional[List[str]] = None,
    ):
        """Initialize CalendarService.

        Args:
            credentials_path: Path to OAuth2 client credentials JSON
            token_path: Path to store refresh token
            timezone: Timezone for events
            default_habit_time: Default time for habit events (HH:MM)
            default_event_duration: Event duration in minutes
            calendar_id: Cached Mazkir calendar ID (optional)
            calendar_include: Allowlist of calendar names to fetch events from (None = all)
        """
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.tz = pytz.timezone(timezone)
        self.timezone = timezone
        self.default_habit_time = default_habit_time
        self.default_event_duration = default_event_duration
        self._calendar_id = calendar_id
        self._calendar_include = calendar_include
        self._service = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the calendar service and authenticate.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            creds = self._get_credentials()
            if not creds:
                logger.error("Failed to get Google credentials")
                return False

            # Create http client with 15 minute timeout
            http = httplib2.Http(timeout=900)
            authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)

            # static_discovery=True avoids network fetch for API schema
            self._service = build('calendar', 'v3', http=authorized_http, static_discovery=True)
            self._initialized = True
            logger.info("Google Calendar service initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize calendar service: {e}")
            return False

    def _get_credentials(self) -> Optional[Credentials]:
        """Get or refresh OAuth2 credentials.

        Returns:
            Credentials object or None if failed
        """
        creds = None

        # Load existing token if available
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            except Exception as e:
                logger.warning(f"Failed to load existing token: {e}")

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    logger.warning(f"Failed to refresh token: {e}")
                    creds = None

            if not creds:
                if not self.credentials_path.exists():
                    logger.error(f"Credentials file not found: {self.credentials_path}")
                    return None

                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.credentials_path), SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    logger.error(f"Failed to run OAuth flow: {e}")
                    return None

            # Save the credentials for next run
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())

        return creds

    async def ensure_mazkir_calendar(self) -> Optional[str]:
        """Create or find the Mazkir calendar.

        Returns:
            Calendar ID or None if failed
        """
        if not self._initialized:
            logger.error("Calendar service not initialized")
            return None

        # Return cached ID if available
        if self._calendar_id:
            try:
                self._service.calendars().get(calendarId=self._calendar_id).execute()
                return self._calendar_id
            except HttpError:
                logger.warning("Cached calendar ID invalid, searching for calendar...")
                self._calendar_id = None

        try:
            # Search for existing Mazkir calendar
            calendar_list = self._service.calendarList().list().execute()
            for calendar in calendar_list.get('items', []):
                if calendar.get('summary') == 'Mazkir':
                    self._calendar_id = calendar['id']
                    logger.info(f"Found existing Mazkir calendar: {self._calendar_id}")
                    return self._calendar_id

            # Create new Mazkir calendar
            calendar_body = {
                'summary': 'Mazkir',
                'description': 'Mazkir Personal AI Assistant - Habits and Tasks',
                'timeZone': self.timezone
            }
            created_calendar = self._service.calendars().insert(body=calendar_body).execute()
            self._calendar_id = created_calendar['id']
            logger.info(f"Created new Mazkir calendar: {self._calendar_id}")
            return self._calendar_id

        except HttpError as e:
            logger.error(f"Failed to ensure Mazkir calendar: {e}")
            return None

    def _frequency_to_rrule(self, frequency: str, scheduled_days: Optional[List[str]] = None) -> Optional[str]:
        """Convert frequency string to RRULE.

        Args:
            frequency: Frequency string (daily, 3x/week, weekly)
            scheduled_days: Optional list of days (monday, tuesday, etc.)

        Returns:
            RRULE string or None
        """
        frequency_lower = frequency.lower()

        if frequency_lower == 'daily':
            return 'RRULE:FREQ=DAILY'
        elif frequency_lower == 'weekly':
            return 'RRULE:FREQ=WEEKLY'
        elif '3x' in frequency_lower or 'three' in frequency_lower:
            # Use scheduled_days if provided, otherwise default to M/W/F
            if scheduled_days:
                days = [self._day_to_rrule_day(d) for d in scheduled_days]
                days_str = ','.join(days)
            else:
                days_str = 'MO,WE,FR'
            return f'RRULE:FREQ=WEEKLY;BYDAY={days_str}'
        elif '2x' in frequency_lower or 'twice' in frequency_lower:
            if scheduled_days:
                days = [self._day_to_rrule_day(d) for d in scheduled_days]
                days_str = ','.join(days)
            else:
                days_str = 'TU,TH'
            return f'RRULE:FREQ=WEEKLY;BYDAY={days_str}'

        return None

    def _day_to_rrule_day(self, day: str) -> str:
        """Convert day name to RRULE day code."""
        day_map = {
            'monday': 'MO', 'mon': 'MO',
            'tuesday': 'TU', 'tue': 'TU',
            'wednesday': 'WE', 'wed': 'WE',
            'thursday': 'TH', 'thu': 'TH',
            'friday': 'FR', 'fri': 'FR',
            'saturday': 'SA', 'sat': 'SA',
            'sunday': 'SU', 'sun': 'SU'
        }
        return day_map.get(day.lower(), 'MO')

    def _build_habit_event(self, habit: Dict) -> Dict:
        """Build a calendar event dict from habit data.

        Args:
            habit: Habit data with metadata

        Returns:
            Google Calendar event dict
        """
        metadata = habit.get('metadata', habit)
        name = metadata.get('name', 'Habit')
        frequency = metadata.get('frequency', 'daily')
        scheduled_time = metadata.get('scheduled_time')  # None by default
        scheduled_days = metadata.get('scheduled_days', [])

        today = datetime.now(self.tz).strftime('%Y-%m-%d')

        # If no scheduled_time, create all-day event
        if not scheduled_time:
            event = {
                'summary': f'🎯 {name}',
                'description': f'Habit: {name}\nFrequency: {frequency}\nManaged by Mazkir',
                'start': {
                    'date': today,
                    'timeZone': self.timezone,
                },
                'end': {
                    'date': today,
                    'timeZone': self.timezone,
                },
                'reminders': {
                    'useDefault': False,
                },
            }
        else:
            # Timed event
            hour, minute = map(int, scheduled_time.split(':'))
            now = datetime.now(self.tz)
            start_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            end_time = start_time + timedelta(minutes=self.default_event_duration)

            event = {
                'summary': f'🎯 {name}',
                'description': f'Habit: {name}\nFrequency: {frequency}\nManaged by Mazkir',
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': self.timezone,
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': self.timezone,
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 10},
                    ],
                },
            }

        # Add recurrence rule
        rrule = self._frequency_to_rrule(frequency, scheduled_days)
        if rrule:
            event['recurrence'] = [rrule]

        return event

    def _build_task_event(self, task: Dict) -> Dict:
        """Build a calendar event dict from task data.

        Args:
            task: Task data with metadata

        Returns:
            Google Calendar event dict
        """
        metadata = task.get('metadata', task)
        name = metadata.get('name', 'Task')
        due_date = metadata.get('due_date')
        priority = metadata.get('priority', 3)

        # Priority emoji
        priority_emoji = {5: '🔴', 4: '🔴', 3: '🟡', 2: '🟢', 1: '🟢'}.get(priority, '🟡')

        # Parse due date - create all-day event for date-only due dates
        if isinstance(due_date, str):
            # Check if it's just a date (YYYY-MM-DD) or includes time
            if 'T' in due_date or ':' in due_date:
                # Has time component
                from dateutil import parser as dateutil_parser
                due_datetime = dateutil_parser.parse(due_date)
                if due_datetime.tzinfo is None:
                    due_datetime = self.tz.localize(due_datetime)

                end_datetime = due_datetime + timedelta(minutes=self.default_event_duration)

                event = {
                    'summary': f'{priority_emoji} {name}',
                    'description': f'Task: {name}\nPriority: {priority}/5\nManaged by Mazkir',
                    'start': {
                        'dateTime': due_datetime.isoformat(),
                        'timeZone': self.timezone,
                    },
                    'end': {
                        'dateTime': end_datetime.isoformat(),
                        'timeZone': self.timezone,
                    },
                    'reminders': {
                        'useDefault': False,
                        'overrides': [
                            {'method': 'popup', 'minutes': 30},
                        ],
                    },
                }
            else:
                # Date only - create all-day event
                event = {
                    'summary': f'{priority_emoji} {name}',
                    'description': f'Task: {name}\nPriority: {priority}/5\nManaged by Mazkir',
                    'start': {
                        'date': due_date,
                        'timeZone': self.timezone,
                    },
                    'end': {
                        'date': due_date,
                        'timeZone': self.timezone,
                    },
                    'reminders': {
                        'useDefault': False,
                        'overrides': [
                            {'method': 'popup', 'minutes': 60},
                        ],
                    },
                }
        else:
            # Fallback to all-day today
            today = datetime.now(self.tz).strftime('%Y-%m-%d')
            event = {
                'summary': f'{priority_emoji} {name}',
                'description': f'Task: {name}\nPriority: {priority}/5\nManaged by Mazkir',
                'start': {
                    'date': today,
                    'timeZone': self.timezone,
                },
                'end': {
                    'date': today,
                    'timeZone': self.timezone,
                },
                'reminders': {
                    'useDefault': False,
                },
            }

        return event

    async def create_habit_event(self, habit: Dict) -> Optional[str]:
        """Create a recurring calendar event for a habit.

        Args:
            habit: Habit data with metadata

        Returns:
            Event ID or None if failed
        """
        if not self._initialized or not self._calendar_id:
            logger.error("Calendar service not properly initialized")
            return None

        try:
            event = self._build_habit_event(habit)
            created_event = self._service.events().insert(
                calendarId=self._calendar_id,
                body=event
            ).execute()
            event_id = created_event.get('id')
            logger.info(f"Created habit event: {event_id}")
            return event_id
        except HttpError as e:
            logger.error(f"Failed to create habit event: {e}")
            return None

    async def create_task_event(self, task: Dict) -> Optional[str]:
        """Create a calendar event for a task with due date.

        Args:
            task: Task data with metadata

        Returns:
            Event ID or None if failed
        """
        if not self._initialized or not self._calendar_id:
            logger.error("Calendar service not properly initialized")
            return None

        try:
            event = self._build_task_event(task)
            created_event = self._service.events().insert(
                calendarId=self._calendar_id,
                body=event
            ).execute()
            event_id = created_event.get('id')
            logger.info(f"Created task event: {event_id}")
            return event_id
        except HttpError as e:
            logger.error(f"Failed to create task event: {e}")
            return None

    def _build_event(self, name: str, date: str, start_time: str, end_time: Optional[str] = None) -> Dict:
        """Build a calendar event dict for a general event.

        Args:
            name: Event name
            date: Date string YYYY-MM-DD
            start_time: Start time HH:MM
            end_time: End time HH:MM (optional, defaults to start + default_event_duration)

        Returns:
            Google Calendar event dict
        """
        start_dt = datetime.strptime(f"{date}T{start_time}:00", "%Y-%m-%dT%H:%M:%S")
        start_dt = self.tz.localize(start_dt)

        if end_time:
            end_dt = datetime.strptime(f"{date}T{end_time}:00", "%Y-%m-%dT%H:%M:%S")
            end_dt = self.tz.localize(end_dt)
        else:
            end_dt = start_dt + timedelta(minutes=self.default_event_duration)

        return {
            'summary': f'📅 {name}',
            'description': f'Event: {name}\nManaged by Mazkir',
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': self.timezone,
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': self.timezone,
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }

    async def create_event(self, name: str, date: str, start_time: str, end_time: Optional[str] = None) -> Optional[str]:
        """Create a calendar event for a general event.

        Args:
            name: Event name
            date: Date string YYYY-MM-DD
            start_time: Start time HH:MM
            end_time: End time HH:MM (optional)

        Returns:
            Event ID or None if failed
        """
        if not self._initialized or not self._calendar_id:
            logger.error("Calendar service not properly initialized")
            return None

        try:
            event = self._build_event(name, date, start_time, end_time)
            created_event = self._service.events().insert(
                calendarId=self._calendar_id,
                body=event
            ).execute()
            event_id = created_event.get('id')
            logger.info(f"Created event: {event_id}")
            return event_id
        except HttpError as e:
            logger.error(f"Failed to create event: {e}")
            return None

    async def mark_event_complete(self, event_id: str, instance_date: Optional[str] = None) -> bool:
        """Mark a calendar event as complete.

        For recurring events, marks the specific instance. Uses green color and ✅ prefix.

        Args:
            event_id: The event ID
            instance_date: For recurring events, the specific date (YYYY-MM-DD)

        Returns:
            True if successful, False otherwise
        """
        if not self._initialized or not self._calendar_id:
            logger.error("Calendar service not properly initialized")
            return False

        try:
            # Get the event
            event = self._service.events().get(
                calendarId=self._calendar_id,
                eventId=event_id
            ).execute()

            # For recurring events with a specific date, get the instance
            if instance_date and 'recurrence' in event:
                # Convert date to RFC3339 format for instance lookup
                instance_datetime = datetime.strptime(instance_date, '%Y-%m-%d')
                instance_datetime = self.tz.localize(instance_datetime)

                # Get instances for this event on this date
                instances = self._service.events().instances(
                    calendarId=self._calendar_id,
                    eventId=event_id,
                    timeMin=instance_datetime.isoformat(),
                    timeMax=(instance_datetime + timedelta(days=1)).isoformat()
                ).execute()

                if instances.get('items'):
                    event = instances['items'][0]
                    event_id = event['id']

            # Update the event
            summary = event.get('summary', '')
            if not summary.startswith('✅'):
                event['summary'] = f"✅ {summary}"
            event['colorId'] = COLOR_GREEN

            self._service.events().update(
                calendarId=self._calendar_id,
                eventId=event_id,
                body=event
            ).execute()

            logger.info(f"Marked event as complete: {event_id}")
            return True

        except HttpError as e:
            logger.error(f"Failed to mark event complete: {e}")
            return False

    async def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event.

        Args:
            event_id: The event ID to delete

        Returns:
            True if successful, False otherwise
        """
        if not self._initialized or not self._calendar_id:
            logger.error("Calendar service not properly initialized")
            return False

        try:
            self._service.events().delete(
                calendarId=self._calendar_id,
                eventId=event_id
            ).execute()
            logger.info(f"Deleted event: {event_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to delete event: {e}")
            return False

    async def get_todays_events(self, all_calendars: bool = True, target_date: date_type | None = None) -> List[Dict]:
        """Get all events for a given date (defaults to today).

        Args:
            all_calendars: If True, fetch from all calendars. If False, only Mazkir.
            target_date: The date to fetch events for. Defaults to today.

        Returns:
            List of event dicts with id, summary, start, end, completed, calendar fields
        """
        if not self._initialized:
            logger.error("Calendar service not initialized")
            return []

        try:
            if target_date:
                start_of_day = datetime(target_date.year, target_date.month, target_date.day, tzinfo=self.tz)
            else:
                now = datetime.now(self.tz)
                start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)

            # Get list of calendars to query
            calendar_ids = []
            if all_calendars:
                calendar_list = self._service.calendarList().list().execute()
                for cal in calendar_list.get('items', []):
                    name = cal.get('summary', 'Unknown')
                    if self._calendar_include and name not in self._calendar_include:
                        continue
                    calendar_ids.append({
                        'id': cal['id'],
                        'name': name,
                    })
            elif self._calendar_id:
                calendar_ids.append({'id': self._calendar_id, 'name': 'Mazkir'})

            events = []
            for cal in calendar_ids:
                try:
                    events_result = self._service.events().list(
                        calendarId=cal['id'],
                        timeMin=start_of_day.isoformat(),
                        timeMax=end_of_day.isoformat(),
                        singleEvents=True,
                        orderBy='startTime'
                    ).execute()

                    for event in events_result.get('items', []):
                        summary = event.get('summary', 'Untitled')
                        completed = summary.startswith('✅') or event.get('colorId') == COLOR_GREEN

                        start = event['start'].get('dateTime', event['start'].get('date'))
                        end = event['end'].get('dateTime', event['end'].get('date'))

                        events.append({
                            'id': event['id'],
                            'summary': summary,
                            'start': start,
                            'end': end,
                            'completed': completed,
                            'calendar': cal['name']
                        })
                except HttpError as e:
                    logger.warning(f"Failed to get events from calendar {cal['name']}: {e}")

            # Sort by start time
            def sort_key(e):
                s = e.get('start', '')
                # All-day events (date only) sort to beginning
                if 'T' not in s:
                    return f"0000-{s}"
                return s

            events.sort(key=sort_key)
            return events

        except HttpError as e:
            logger.error(f"Failed to get today's events: {e}")
            return []

    async def sync_habit(self, habit: Dict) -> Optional[str]:
        """Sync a habit to calendar (create or update).

        Args:
            habit: Habit data with metadata

        Returns:
            Event ID or None if failed
        """
        metadata = habit.get('metadata', habit)
        existing_event_id = metadata.get('google_event_id')

        if existing_event_id:
            # Update existing event
            try:
                event = self._build_habit_event(habit)
                self._service.events().update(
                    calendarId=self._calendar_id,
                    eventId=existing_event_id,
                    body=event
                ).execute()
                logger.info(f"Updated habit event: {existing_event_id}")
                return existing_event_id
            except HttpError as e:
                logger.warning(f"Failed to update habit event, creating new: {e}")

        # Create new event
        return await self.create_habit_event(habit)

    async def sync_task(self, task: Dict) -> Optional[str]:
        """Sync a task to calendar (create or update).

        Args:
            task: Task data with metadata

        Returns:
            Event ID or None if failed
        """
        metadata = task.get('metadata', task)
        existing_event_id = metadata.get('google_event_id')

        # Only sync tasks with due dates
        if not metadata.get('due_date'):
            return None

        if existing_event_id:
            # Update existing event
            try:
                event = self._build_task_event(task)
                self._service.events().update(
                    calendarId=self._calendar_id,
                    eventId=existing_event_id,
                    body=event
                ).execute()
                logger.info(f"Updated task event: {existing_event_id}")
                return existing_event_id
            except HttpError as e:
                logger.warning(f"Failed to update task event, creating new: {e}")

        # Create new event
        return await self.create_task_event(task)

    @property
    def is_initialized(self) -> bool:
        """Check if the service is initialized."""
        return self._initialized

    @property
    def calendar_id(self) -> Optional[str]:
        """Get the Mazkir calendar ID."""
        return self._calendar_id
