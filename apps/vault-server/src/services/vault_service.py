from pathlib import Path
from datetime import datetime
import frontmatter
import pytz
import re
from typing import Dict, List, Optional


class VaultService:
    """Service for reading and writing to Obsidian vault"""

    def __init__(self, vault_path: Path, timezone: str = "Asia/Jerusalem"):
        self.vault_path = Path(vault_path)
        self.tz = pytz.timezone(timezone)

        # Verify vault exists
        if not self.vault_path.exists():
            raise FileNotFoundError(f"Vault not found: {vault_path}")

        # Verify AGENTS.md exists
        agents_md = self.vault_path / "AGENTS.md"
        if not agents_md.exists():
            raise FileNotFoundError("AGENTS.md not found in vault")

    def read_file(self, relative_path: str) -> Dict:
        """Read a markdown file and parse frontmatter

        Args:
            relative_path: Path relative to vault root (e.g., "10-daily/2026-01-07.md")

        Returns:
            Dict with 'metadata' (frontmatter) and 'content' (body)
        """
        file_path = self.vault_path / relative_path

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)

        return {
            'metadata': dict(post.metadata),
            'content': post.content,
            'path': relative_path
        }

    def write_file(self, relative_path: str, metadata: Dict, content: str):
        """Write a markdown file with frontmatter

        Args:
            relative_path: Path relative to vault root
            metadata: Dictionary of frontmatter fields
            content: Markdown body content
        """
        file_path = self.vault_path / relative_path

        # Ensure directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Always update 'updated' timestamp
        metadata['updated'] = datetime.now(self.tz).strftime('%Y-%m-%d')

        # Create frontmatter post
        post = frontmatter.Post(content, **metadata)

        # Write to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post))

    def update_file(self, relative_path: str, metadata_updates: Dict):
        """Update frontmatter of existing file

        Args:
            relative_path: Path relative to vault root
            metadata_updates: Dictionary of fields to update
        """
        # Read existing
        file_data = self.read_file(relative_path)

        # Update metadata
        file_data['metadata'].update(metadata_updates)

        # Write back
        self.write_file(relative_path, file_data['metadata'], file_data['content'])

    def list_files(self, directory: str, pattern: str = "*.md") -> List[Path]:
        """List files in a directory

        Args:
            directory: Directory relative to vault root
            pattern: Glob pattern for files

        Returns:
            List of Path objects relative to vault root
        """
        dir_path = self.vault_path / directory

        if not dir_path.exists():
            return []

        files = list(dir_path.glob(pattern))

        # Return paths relative to vault root
        return [f.relative_to(self.vault_path) for f in files]

    # Convenience methods for common operations

    def get_daily_note_path(self, date: Optional[datetime] = None) -> str:
        """Get path to daily note for given date"""
        if date is None:
            date = datetime.now(self.tz)
        return f"10-daily/{date.strftime('%Y-%m-%d')}.md"

    def read_daily_note(self, date: Optional[datetime] = None) -> Dict:
        """Read daily note for given date"""
        path = self.get_daily_note_path(date)
        return self.read_file(path)

    def read_habit(self, habit_name: str) -> Dict:
        """Read habit file

        Args:
            habit_name: Name of habit (e.g., 'gym-workout')
        """
        return self.read_file(f"20-habits/{habit_name}.md")

    def update_habit(self, habit_name: str, updates: Dict) -> Dict:
        """Update habit file and return updated data"""
        path = f"20-habits/{habit_name}.md"
        self.update_file(path, updates)
        return self.read_file(path)

    def list_active_habits(self) -> List[Dict]:
        """Get all active habits with their data"""
        habit_files = self.list_files("20-habits")
        habits = []

        for file_path in habit_files:
            data = self.read_file(str(file_path))
            if data['metadata'].get('status') == 'active':
                habits.append(data)

        return habits

    def list_active_tasks(self) -> List[Dict]:
        """Get all active tasks"""
        task_files = self.list_files("40-tasks/active")
        tasks = []

        for file_path in task_files:
            data = self.read_file(str(file_path))
            tasks.append(data)

        # Sort by priority (high to low) then due_date
        def sort_key(task):
            from datetime import date
            priority = task['metadata'].get('priority', 3)
            due_date = task['metadata'].get('due_date')

            # Convert due_date to comparable format
            if due_date is None:
                due_date_sort = date(9999, 12, 31)  # Far future for tasks without due dates
            elif isinstance(due_date, str):
                from dateutil import parser
                due_date_sort = parser.parse(due_date).date()
            elif isinstance(due_date, date):
                due_date_sort = due_date
            else:
                due_date_sort = date(9999, 12, 31)

            return (-priority, due_date_sort)

        return sorted(tasks, key=sort_key)

    def list_active_goals(self) -> List[Dict]:
        """Get all active goals (not completed or archived)"""
        from datetime import datetime

        # Get current year
        current_year = datetime.now(self.tz).year

        # Look for goals in current year directory
        goal_files = self.list_files(f"30-goals/{current_year}")
        goals = []

        for file_path in goal_files:
            data = self.read_file(str(file_path))
            status = data['metadata'].get('status', '').lower()

            # Include goals that are in-progress or not-started
            if status in ['in-progress', 'not-started', 'active', 'planning']:
                goals.append(data)

        # Sort by priority (high to low) then progress (low to high)
        def sort_key(goal):
            priority_map = {'high': 3, 'medium': 2, 'low': 1}
            priority = priority_map.get(goal['metadata'].get('priority', 'medium').lower(), 2)
            progress = goal['metadata'].get('progress', 0)
            return (-priority, progress)

        return sorted(goals, key=sort_key)

    def read_token_ledger(self) -> Dict:
        """Read motivation tokens ledger"""
        return self.read_file("00-system/motivation-tokens.md")

    def update_tokens(self, tokens_earned: int, activity: str) -> Dict:
        """Award tokens and update ledger

        Args:
            tokens_earned: Amount of tokens to award
            activity: Description of activity

        Returns:
            Updated token data
        """
        # Read current ledger
        ledger = self.read_token_ledger()
        metadata = ledger['metadata']

        # Reset tokens_today if it's a new day
        today = datetime.now(self.tz).strftime('%Y-%m-%d')
        last_updated = str(metadata.get('updated', ''))
        if last_updated != today:
            prior_today = 0
        else:
            prior_today = metadata.get('tokens_today', 0)

        # Update totals
        old_total = metadata.get('total_tokens', 0)
        new_total = old_total + tokens_earned
        tokens_today = prior_today + tokens_earned

        # Update metadata
        updates = {
            'total_tokens': new_total,
            'tokens_today': tokens_today,
            'all_time_tokens': metadata.get('all_time_tokens', 0) + tokens_earned
        }

        self.update_file("00-system/motivation-tokens.md", updates)

        # Add transaction to today's daily note
        try:
            daily = self.read_daily_note()
            daily_metadata = daily['metadata']

            daily_updates = {
                'tokens_earned': daily_metadata.get('tokens_earned', 0) + tokens_earned,
                'tokens_total': new_total
            }

            self.update_file(self.get_daily_note_path(), daily_updates)
        except FileNotFoundError:
            # Daily note doesn't exist yet - that's okay
            pass

        return {
            'tokens_earned': tokens_earned,
            'old_total': old_total,
            'new_total': new_total,
            'activity': activity
        }

    # =========================================================================
    # Template-based creation methods
    # =========================================================================

    def _load_template(self, template_name: str) -> Dict:
        """Load a template file and return metadata and content

        Args:
            template_name: Template filename (e.g., '_task_.md')

        Returns:
            Dict with 'metadata' and 'content'
        """
        template_path = f"00-system/templates/{template_name}"
        return self.read_file(template_path)

    def _process_template(self, template: Dict, substitutions: Dict) -> Dict:
        """Process template by replacing placeholders

        Args:
            template: Dict with 'metadata' and 'content'
            substitutions: Dict of placeholder -> value mappings

        Returns:
            Dict with processed 'metadata' and 'content'
        """
        metadata = template['metadata'].copy()
        content = template['content']

        # Process content placeholders
        for key, value in substitutions.items():
            placeholder = "{{" + key + "}}"
            content = content.replace(placeholder, str(value) if value else "")

            # Also process metadata string values
            for meta_key, meta_value in metadata.items():
                if isinstance(meta_value, str) and placeholder in meta_value:
                    metadata[meta_key] = meta_value.replace(placeholder, str(value) if value else "")

        return {
            'metadata': metadata,
            'content': content
        }

    def _sanitize_filename(self, name: str, max_length: int = 50) -> str:
        """Convert a name to a valid filename

        Args:
            name: Original name
            max_length: Maximum filename length

        Returns:
            Sanitized filename (without extension)
        """
        # Remove special characters
        filename = re.sub(r'[^\w\s-]', '', name)
        # Replace spaces with hyphens
        filename = re.sub(r'[-\s]+', '-', filename)
        # Lowercase
        filename = filename.lower().strip('-')
        # Limit length
        return filename[:max_length]

    def create_task(self, name: str, priority: int = 3, due_date: str = None,
                    category: str = "personal", tokens_on_completion: int = 5) -> Dict:
        """Create a new task using template

        Args:
            name: Task name/description
            priority: 1-5 (5=highest)
            due_date: Optional due date (YYYY-MM-DD)
            category: work, personal, health, learning
            tokens_on_completion: Tokens awarded when done

        Returns:
            Dict with created task data and path
        """
        today = datetime.now(self.tz).strftime('%Y-%m-%d')

        # Load and process template
        template = self._load_template('_task_.md')
        processed = self._process_template(template, {
            'title': name,
            'date': today
        })

        # Override metadata with provided values
        metadata = processed['metadata']
        metadata['type'] = 'task'
        metadata['name'] = name
        metadata['status'] = 'active'
        metadata['priority'] = priority
        metadata['due_date'] = due_date
        metadata['category'] = category
        metadata['tokens_on_completion'] = tokens_on_completion
        metadata['tags'] = ['task', category]
        metadata['created'] = today
        metadata['updated'] = today

        # Generate filename and path
        filename = self._sanitize_filename(name)
        task_path = f"40-tasks/active/{filename}.md"

        # Write file
        self.write_file(task_path, metadata, processed['content'])

        return {
            'path': task_path,
            'metadata': metadata,
            'content': processed['content']
        }

    def create_habit(self, name: str, frequency: str = "daily",
                     category: str = "personal", difficulty: str = "medium",
                     tokens_per_completion: int = 5) -> Dict:
        """Create a new habit using template

        Args:
            name: Habit name
            frequency: daily, 3x/week, weekly, etc.
            category: health, learning, productivity, personal
            difficulty: easy, medium, hard
            tokens_per_completion: Tokens per completion

        Returns:
            Dict with created habit data and path
        """
        today = datetime.now(self.tz).strftime('%Y-%m-%d')

        # Load and process template
        template = self._load_template('_habit_.md')
        processed = self._process_template(template, {
            'title': name,
            'date': today
        })

        # Override metadata
        metadata = processed['metadata']
        metadata['type'] = 'habit'
        metadata['name'] = name
        metadata['frequency'] = frequency
        metadata['streak'] = 0
        metadata['longest_streak'] = 0
        metadata['last_completed'] = None
        metadata['status'] = 'active'
        metadata['category'] = category
        metadata['difficulty'] = difficulty
        metadata['tokens_per_completion'] = tokens_per_completion
        metadata['tags'] = ['habit', category]
        metadata['created'] = today
        metadata['updated'] = today

        # Generate filename and path
        filename = self._sanitize_filename(name)
        habit_path = f"20-habits/{filename}.md"

        # Write file
        self.write_file(habit_path, metadata, processed['content'])

        return {
            'path': habit_path,
            'metadata': metadata,
            'content': processed['content']
        }

    def create_goal(self, name: str, priority: str = "medium",
                    target_date: str = None, category: str = "personal") -> Dict:
        """Create a new goal using template

        Args:
            name: Goal name
            priority: high, medium, low
            target_date: Optional target completion date (YYYY-MM-DD)
            category: career, health, learning, finance, personal

        Returns:
            Dict with created goal data and path
        """
        now = datetime.now(self.tz)
        today = now.strftime('%Y-%m-%d')
        current_year = now.year

        # Load and process template
        template = self._load_template('_goal_.md')
        processed = self._process_template(template, {
            'title': name,
            'date': today
        })

        # Override metadata
        metadata = processed['metadata']
        metadata['type'] = 'goal'
        metadata['name'] = name
        metadata['status'] = 'not-started'
        metadata['priority'] = priority
        metadata['start_date'] = today
        metadata['target_date'] = target_date
        metadata['progress'] = 0
        metadata['category'] = category
        metadata['tags'] = ['goal', category]
        metadata['milestones'] = []
        metadata['related_tasks'] = []
        metadata['created'] = today
        metadata['updated'] = today

        # Generate filename and path
        filename = self._sanitize_filename(name)
        goal_path = f"30-goals/{current_year}/{filename}.md"

        # Write file
        self.write_file(goal_path, metadata, processed['content'])

        return {
            'path': goal_path,
            'metadata': metadata,
            'content': processed['content']
        }

    def create_daily_note(self, date: datetime = None) -> Dict:
        """Create a daily note using template

        Args:
            date: Date for the note (defaults to today)

        Returns:
            Dict with created daily note data and path
        """
        if date is None:
            date = datetime.now(self.tz)

        date_str = date.strftime('%Y-%m-%d')
        day_name = date.strftime('%A')
        date_formatted = date.strftime('%B %d, %Y')

        # Load and process template
        template = self._load_template('_daily_.md')
        processed = self._process_template(template, {
            'date': date_str,
            'day': day_name[:3],  # Mon, Tue, etc.
            'day_full': day_name,
            'date_formatted': date_formatted
        })

        # Get current token balance
        try:
            ledger = self.read_token_ledger()
            tokens_total = ledger['metadata'].get('total_tokens', 0)
        except FileNotFoundError:
            tokens_total = 0

        # Override metadata
        metadata = processed['metadata']
        metadata['type'] = 'daily'
        metadata['date'] = date_str
        metadata['day_of_week'] = day_name
        metadata['tokens_earned'] = 0
        metadata['tokens_total'] = tokens_total
        metadata['mood'] = None
        metadata['energy'] = None
        metadata['completed_habits'] = []
        metadata['tags'] = ['daily']
        metadata['created'] = date_str
        metadata['updated'] = date_str

        # Update content with token total
        content = processed['content']
        content = content.replace('**Total Bank:** 0 tokens', f'**Total Bank:** {tokens_total} tokens')

        # Generate path
        daily_path = f"10-daily/{date_str}.md"

        # Write file
        self.write_file(daily_path, metadata, content)

        return {
            'path': daily_path,
            'metadata': metadata,
            'content': content
        }

    def complete_task(self, task_path: str, award_tokens: bool = True) -> Dict:
        """Mark a task as complete and move to archive

        Args:
            task_path: Path to task file (relative to vault)
            award_tokens: Whether to award tokens for completion

        Returns:
            Dict with completion info
        """
        # Read task
        task = self.read_file(task_path)
        metadata = task['metadata']

        # Get task name
        task_name = metadata.get('name', 'Task')

        # Award tokens if requested
        tokens_earned = 0
        if award_tokens:
            tokens_earned = metadata.get('tokens_on_completion', 5)
            self.update_tokens(tokens_earned, f"Completed: {task_name}")

        # Update metadata
        today = datetime.now(self.tz).strftime('%Y-%m-%d')
        metadata['status'] = 'done'
        metadata['completed_date'] = today
        metadata['updated'] = today

        # Generate archive path
        filename = Path(task_path).name
        archive_path = f"40-tasks/archive/{filename}"

        # Write to archive
        self.write_file(archive_path, metadata, task['content'])

        # Delete from active
        active_file = self.vault_path / task_path
        if active_file.exists():
            active_file.unlink()

        return {
            'task_name': task_name,
            'tokens_earned': tokens_earned,
            'archive_path': archive_path
        }

    def find_task_by_name(self, name: str) -> Optional[Dict]:
        """Find a task by name (fuzzy match)

        Args:
            name: Task name to search for

        Returns:
            Task dict if found, None otherwise
        """
        tasks = self.list_active_tasks()
        name_lower = name.lower()

        for task in tasks:
            task_name = task['metadata'].get('name', '')
            # Also check content for heading
            if not task_name:
                content = task.get('content', '')
                for line in content.split('\n'):
                    if line.startswith('#'):
                        task_name = line.lstrip('#').strip()
                        break

            if task_name and (name_lower in task_name.lower() or task_name.lower() in name_lower):
                return task

        return None

    # =========================================================================
    # Calendar sync helper methods
    # =========================================================================

    def get_habits_needing_sync(self) -> List[Dict]:
        """Get all active habits without a google_event_id

        Returns:
            List of habit dicts needing calendar sync
        """
        habits = self.list_active_habits()
        return [h for h in habits if not h['metadata'].get('google_event_id')]

    def get_tasks_needing_sync(self) -> List[Dict]:
        """Get all active tasks with due_date but no google_event_id

        Returns:
            List of task dicts needing calendar sync
        """
        tasks = self.list_active_tasks()
        return [
            t for t in tasks
            if t['metadata'].get('due_date') and not t['metadata'].get('google_event_id')
        ]

    def update_google_event_id(self, file_path: str, event_id: str):
        """Store Google Calendar event ID in file frontmatter

        Args:
            file_path: Path to file (relative to vault)
            event_id: Google Calendar event ID
        """
        self.update_file(file_path, {'google_event_id': event_id})
