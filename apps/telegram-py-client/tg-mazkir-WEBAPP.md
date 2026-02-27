# Telegram WebApp Specification

**Project:** tg-mazkir WebApp  
**Phase:** 3 - Telegram WebApp  
**Component:** Daily Note Viewer  

---

## Overview

A Telegram WebApp that renders the current daily note in an engaging, interactive format. Telegram WebApps are HTML/CSS/JS applications that run inside the Telegram client and can communicate with the bot.

---

## Architecture

```
┌─────────────────────────────────┐
│    Telegram Client (Mobile)     │
│  ┌───────────────────────────┐  │
│  │   WebApp (HTML/CSS/JS)    │  │
│  │                           │  │
│  │  Daily Note Renderer      │  │
│  │                           │  │
│  └──────────┬────────────────┘  │
└─────────────┼───────────────────┘
              │ Telegram WebApp API
      ┌───────▼────────┐
      │  tg-mazkir Bot │
      │   (Backend)    │
      └───────┬────────┘
              │
      ┌───────▼────────┐
      │ Obsidian Vault │
      └────────────────┘
```

---

## Tech Stack

**Frontend:**
- HTML5
- CSS3 (Tailwind CDN for rapid styling)
- Vanilla JavaScript (no framework needed for MVP)
- Telegram WebApp JS library

**Backend:**
- FastAPI (lightweight Python web server)
- Serves WebApp static files
- Provides API endpoints for data

**Communication:**
- Telegram WebApp → tg-mazkir bot (via `window.Telegram.WebApp`)
- tg-mazkir bot → Vault (direct filesystem)

---

## File Structure

```
src/webapp/
├── static/
│   ├── css/
│   │   └── daily-note.css
│   ├── js/
│   │   ├── telegram-web-app.js  # Telegram's library
│   │   └── daily-note.js
│   └── images/
│       ├── icon-tokens.svg
│       ├── icon-habits.svg
│       └── icon-tasks.svg
│
├── templates/
│   └── daily-note.html
│
└── server.py  # FastAPI server
```

---

## Phase 1: Daily Note Viewer (MVP)

### Features

✅ **Display Today's Daily Note**
- Date and day of week
- Token balance (today + total)
- Habit checklist with streaks
- Task list
- Food log
- Notes section

✅ **Interactive Elements**
- Toggle habit completion
- Check off tasks
- Smooth animations
- Pull-to-refresh

✅ **Visual Design**
- Card-based layout
- Progress rings for habits
- Token counter animation
- Mobile-first responsive

---

## Implementation

### 1. HTML Template

**File:** `src/webapp/templates/daily-note.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Daily Note</title>
    
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    
    <!-- Telegram WebApp JS -->
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    
    <!-- Custom CSS -->
    <link rel="stylesheet" href="/static/css/daily-note.css">
</head>
<body class="bg-gradient-to-br from-blue-50 to-indigo-100 min-h-screen">
    <div id="app" class="container mx-auto px-4 py-6 max-w-md">
        
        <!-- Loading State -->
        <div id="loading" class="flex items-center justify-center h-screen">
            <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600"></div>
        </div>
        
        <!-- Main Content (hidden until loaded) -->
        <div id="content" class="hidden space-y-4">
            
            <!-- Header -->
            <div class="bg-white rounded-2xl shadow-lg p-6">
                <div class="text-center">
                    <div id="day-name" class="text-3xl font-bold text-gray-800"></div>
                    <div id="date" class="text-gray-500 mt-1"></div>
                </div>
            </div>
            
            <!-- Tokens Card -->
            <div class="bg-gradient-to-r from-yellow-400 to-orange-500 rounded-2xl shadow-lg p-6 text-white">
                <div class="flex items-center justify-between">
                    <div>
                        <div class="text-sm opacity-90">Tokens Today</div>
                        <div id="tokens-today" class="text-4xl font-bold">0</div>
                    </div>
                    <div class="text-right">
                        <div class="text-sm opacity-90">Total Bank</div>
                        <div id="tokens-total" class="text-2xl font-bold">0</div>
                    </div>
                </div>
                
                <!-- Token animation container -->
                <div id="token-animation" class="mt-4 h-2 bg-white/20 rounded-full overflow-hidden">
                    <div id="token-progress" class="h-full bg-white rounded-full transition-all duration-500" style="width: 0%"></div>
                </div>
            </div>
            
            <!-- Habits Card -->
            <div class="bg-white rounded-2xl shadow-lg p-6">
                <h2 class="text-xl font-bold text-gray-800 mb-4 flex items-center">
                    <span class="mr-2">🎯</span> Daily Habits
                </h2>
                <div id="habits-list" class="space-y-3">
                    <!-- Habits will be inserted here -->
                </div>
            </div>
            
            <!-- Tasks Card -->
            <div class="bg-white rounded-2xl shadow-lg p-6">
                <h2 class="text-xl font-bold text-gray-800 mb-4 flex items-center">
                    <span class="mr-2">📋</span> Tasks
                </h2>
                <div id="tasks-list" class="space-y-2">
                    <!-- Tasks will be inserted here -->
                </div>
            </div>
            
            <!-- Food Log Card -->
            <div class="bg-white rounded-2xl shadow-lg p-6">
                <h2 class="text-xl font-bold text-gray-800 mb-4 flex items-center">
                    <span class="mr-2">🍽️</span> Food Log
                </h2>
                <div id="food-log" class="space-y-3">
                    <!-- Food entries will be inserted here -->
                </div>
            </div>
            
            <!-- Notes Card -->
            <div class="bg-white rounded-2xl shadow-lg p-6">
                <h2 class="text-xl font-bold text-gray-800 mb-4 flex items-center">
                    <span class="mr-2">💭</span> Notes
                </h2>
                <div id="notes-content" class="text-gray-600 whitespace-pre-wrap">
                    <!-- Notes will be inserted here -->
                </div>
            </div>
            
        </div>
    </div>
    
    <!-- Custom JS -->
    <script src="/static/js/daily-note.js"></script>
</body>
</html>
```

### 2. JavaScript

**File:** `src/webapp/static/js/daily-note.js`

```javascript
// Initialize Telegram WebApp
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

// State
let dailyNoteData = null;

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    try {
        // Fetch daily note data from bot
        await loadDailyNote();
        
        // Render content
        renderDailyNote();
        
        // Show content, hide loading
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('content').classList.remove('hidden');
        
    } catch (error) {
        console.error('Error loading daily note:', error);
        tg.showAlert('Failed to load daily note');
    }
});

async function loadDailyNote() {
    // Request data from bot via Telegram WebApp API
    // The bot will receive this request and respond with data
    
    const response = await fetch('/api/daily-note', {
        headers: {
            'X-Telegram-Init-Data': tg.initData
        }
    });
    
    if (!response.ok) {
        throw new Error('Failed to fetch daily note');
    }
    
    dailyNoteData = await response.json();
}

function renderDailyNote() {
    const { metadata, content } = dailyNoteData;
    
    // Render date
    document.getElementById('day-name').textContent = metadata.day_of_week;
    document.getElementById('date').textContent = formatDate(metadata.date);
    
    // Render tokens
    renderTokens(metadata.tokens_earned, metadata.tokens_total);
    
    // Render habits
    renderHabits(dailyNoteData.habits, metadata.completed_habits);
    
    // Render tasks
    renderTasks(dailyNoteData.tasks);
    
    // Render food log (parse from content)
    renderFoodLog(content);
    
    // Render notes
    renderNotes(content);
}

function renderTokens(today, total) {
    const todayEl = document.getElementById('tokens-today');
    const totalEl = document.getElementById('tokens-total');
    const progressEl = document.getElementById('token-progress');
    
    // Animate counter
    animateNumber(todayEl, 0, today, 1000);
    animateNumber(totalEl, 0, total, 1500);
    
    // Animate progress bar (towards next milestone)
    const nextMilestone = Math.ceil(total / 50) * 50;
    const progress = (total % 50) / 50 * 100;
    
    setTimeout(() => {
        progressEl.style.width = `${progress}%`;
    }, 500);
}

function renderHabits(habits, completedHabits) {
    const container = document.getElementById('habits-list');
    container.innerHTML = '';
    
    habits.forEach(habit => {
        const isCompleted = completedHabits.includes(habit.name);
        
        const habitEl = document.createElement('div');
        habitEl.className = `habit-item flex items-center justify-between p-4 rounded-xl transition-all ${
            isCompleted ? 'bg-green-50 border-2 border-green-500' : 'bg-gray-50 border-2 border-gray-200'
        }`;
        
        habitEl.innerHTML = `
            <div class="flex items-center space-x-3">
                <div class="checkbox ${isCompleted ? 'checked' : ''}" data-habit="${habit.name}">
                    ${isCompleted ? '✓' : ''}
                </div>
                <div>
                    <div class="font-semibold text-gray-800">${habit.name}</div>
                    <div class="text-sm text-gray-500">🔥 ${habit.streak} day streak</div>
                </div>
            </div>
            <div class="text-yellow-600 font-bold">+${habit.tokens_per_completion}</div>
        `;
        
        // Add click handler for toggling
        const checkbox = habitEl.querySelector('.checkbox');
        checkbox.addEventListener('click', () => toggleHabit(habit.name, isCompleted));
        
        container.appendChild(habitEl);
    });
}

function renderTasks(tasks) {
    const container = document.getElementById('tasks-list');
    container.innerHTML = '';
    
    if (tasks.length === 0) {
        container.innerHTML = '<div class="text-gray-400 text-center py-4">No tasks for today</div>';
        return;
    }
    
    tasks.forEach(task => {
        const taskEl = document.createElement('div');
        taskEl.className = 'flex items-center space-x-3 p-3 hover:bg-gray-50 rounded-lg transition-colors';
        
        const priorityColor = {
            5: 'text-red-500',
            4: 'text-red-400',
            3: 'text-yellow-500',
            2: 'text-green-500',
            1: 'text-green-400'
        }[task.priority] || 'text-gray-500';
        
        taskEl.innerHTML = `
            <input type="checkbox" class="w-5 h-5 rounded border-gray-300" data-task="${task.name}">
            <div class="flex-1">
                <div class="text-gray-800">${task.name}</div>
                ${task.due_date ? `<div class="text-xs text-gray-500">Due: ${task.due_date}</div>` : ''}
            </div>
            <div class="${priorityColor}">●</div>
        `;
        
        container.appendChild(taskEl);
    });
}

function renderFoodLog(content) {
    const container = document.getElementById('food-log');
    
    // Parse food log from markdown content
    // This is simplified - you might want better parsing
    const meals = {
        'Breakfast': 'Not logged',
        'Lunch': 'Not logged',
        'Dinner': 'Not logged'
    };
    
    // Try to extract from content
    const foodSection = content.match(/## 🍽️ Food\n([\s\S]*?)(?=\n## |$)/);
    if (foodSection) {
        const text = foodSection[1];
        const breakfastMatch = text.match(/### Breakfast\n- (.+)/);
        const lunchMatch = text.match(/### Lunch\n- (.+)/);
        const dinnerMatch = text.match(/### Dinner\n- (.+)/);
        
        if (breakfastMatch) meals.Breakfast = breakfastMatch[1];
        if (lunchMatch) meals.Lunch = lunchMatch[1];
        if (dinnerMatch) meals.Dinner = dinnerMatch[1];
    }
    
    container.innerHTML = Object.entries(meals).map(([meal, food]) => `
        <div class="border-l-4 border-indigo-500 pl-4 py-2">
            <div class="font-semibold text-gray-700">${meal}</div>
            <div class="text-gray-600">${food}</div>
        </div>
    `).join('');
}

function renderNotes(content) {
    const container = document.getElementById('notes-content');
    
    // Extract notes section from content
    const notesMatch = content.match(/## 💭 Notes\n([\s\S]*?)(?=\n## |$)/);
    
    if (notesMatch && notesMatch[1].trim()) {
        container.textContent = notesMatch[1].trim();
    } else {
        container.textContent = 'No notes for today';
        container.classList.add('text-gray-400', 'italic');
    }
}

// Helper functions

function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { 
        month: 'long', 
        day: 'numeric', 
        year: 'numeric' 
    });
}

function animateNumber(element, start, end, duration) {
    const startTime = performance.now();
    
    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        
        const current = Math.floor(start + (end - start) * easeOutQuad(progress));
        element.textContent = current;
        
        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }
    
    requestAnimationFrame(update);
}

function easeOutQuad(t) {
    return t * (2 - t);
}

async function toggleHabit(habitName, currentState) {
    try {
        // Show loading feedback
        tg.HapticFeedback.impactOccurred('medium');
        
        // Call bot API to toggle habit
        const response = await fetch('/api/toggle-habit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Telegram-Init-Data': tg.initData
            },
            body: JSON.stringify({ 
                habit: habitName,
                completed: !currentState
            })
        });
        
        if (response.ok) {
            // Reload data and re-render
            await loadDailyNote();
            renderDailyNote();
            
            tg.HapticFeedback.notificationOccurred('success');
        } else {
            tg.showAlert('Failed to update habit');
        }
        
    } catch (error) {
        console.error('Error toggling habit:', error);
        tg.showAlert('Error updating habit');
    }
}
```

### 3. CSS Styling

**File:** `src/webapp/static/css/daily-note.css`

```css
/* Custom animations and styles */

.checkbox {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    border: 2px solid #d1d5db;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    transition: all 0.3s ease;
    cursor: pointer;
}

.checkbox.checked {
    background: linear-gradient(135deg, #10b981, #059669);
    border-color: #059669;
    color: white;
}

.checkbox:active {
    transform: scale(0.9);
}

.habit-item {
    animation: slideIn 0.3s ease-out;
}

@keyframes slideIn {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* Smooth scrolling */
html {
    scroll-behavior: smooth;
}

/* Custom scrollbar */
::-webkit-scrollbar {
    width: 8px;
}

::-webkit-scrollbar-track {
    background: #f1f5f9;
}

::-webkit-scrollbar-thumb {
    background: #cbd5e1;
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: #94a3b8;
}
```

### 4. Backend API Server

**File:** `src/webapp/server.py`

```python
from fastapi import FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
from src.services.vault_service import VaultService
from src.config import config
import hmac
import hashlib
import urllib.parse

app = FastAPI()

# Mount static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Initialize vault service
vault = VaultService(config.VAULT_PATH, config.VAULT_TIMEZONE)


def verify_telegram_webapp_data(init_data: str) -> bool:
    """Verify that request came from Telegram WebApp"""
    # Parse init_data
    params = dict(urllib.parse.parse_qsl(init_data))
    
    # Extract and remove hash
    received_hash = params.pop('hash', None)
    if not received_hash:
        return False
    
    # Create data-check-string
    data_check_arr = [f"{k}={v}" for k, v in sorted(params.items())]
    data_check_string = '\n'.join(data_check_arr)
    
    # Calculate expected hash
    secret_key = hmac.new(
        "WebAppData".encode(),
        config.TELEGRAM_BOT_TOKEN.encode(),
        hashlib.sha256
    ).digest()
    
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return received_hash == expected_hash


@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    """Serve the WebApp HTML"""
    template_path = Path(__file__).parent / "templates" / "daily-note.html"
    with open(template_path, 'r') as f:
        return f.read()


@app.get("/api/daily-note")
async def get_daily_note(x_telegram_init_data: str = Header(None)):
    """API endpoint to get daily note data"""
    
    # Verify request is from Telegram
    if not verify_telegram_webapp_data(x_telegram_init_data):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        # Read daily note
        daily = vault.read_daily_note()
        
        # Read habits
        habits = vault.list_active_habits()
        habits_data = [{
            'name': h['metadata']['name'],
            'streak': h['metadata'].get('streak', 0),
            'tokens_per_completion': h['metadata'].get('tokens_per_completion', 5)
        } for h in habits]
        
        # Read tasks
        tasks = vault.list_active_tasks()
        tasks_data = [{
            'name': t['metadata']['name'],
            'priority': t['metadata'].get('priority', 3),
            'due_date': t['metadata'].get('due_date')
        } for t in tasks]
        
        return JSONResponse({
            'metadata': daily['metadata'],
            'content': daily['content'],
            'habits': habits_data,
            'tasks': tasks_data
        })
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Daily note not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/toggle-habit")
async def toggle_habit(
    request: dict,
    x_telegram_init_data: str = Header(None)
):
    """Toggle habit completion"""
    
    # Verify request
    if not verify_telegram_webapp_data(x_telegram_init_data):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    habit_name = request.get('habit')
    completed = request.get('completed', False)
    
    try:
        # This would call the same logic as the bot's habit completion
        # For now, simplified version
        
        if completed:
            # Mark habit as completed
            # Award tokens
            # Update daily note
            pass
        else:
            # Unmark habit
            # Remove from completed list
            pass
        
        return JSONResponse({'success': True})
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## Telegram Bot Integration

To open the WebApp from the bot, add this to your command handlers:

```python
from telethon import Button

@events.register(events.NewMessage(pattern='/day'))
@authorized_only
async def cmd_day(event):
    """Show today's daily note"""
    
    # Inline button to open WebApp
    webapp_button = Button.url(
        "📱 Open Interactive View",
        f"https://your-server.com/"  # Your WebApp URL
    )
    
    # Send message with button
    await event.respond(
        "📅 Today's Daily Note\n\n"
        "Choose a view:",
        buttons=[[webapp_button]]
    )
```

---

## Deployment

### Option 1: Local Development

```bash
# Run FastAPI server
cd src/webapp
python server.py

# Access at http://localhost:8000
```

### Option 2: Production (ngrok for testing)

```bash
# Install ngrok
# https://ngrok.com/

# Expose local server
ngrok http 8000

# Use ngrok URL in bot
```

### Option 3: Production (VPS)

```bash
# Deploy to VPS with nginx reverse proxy
# SSL certificate required for Telegram WebApp
```

---

## Future Enhancements

**Phase 2 Features:**
- Edit daily note inline
- Add tasks via form
- Interactive habit calendar (GitHub-style grid)
- Token history chart (Chart.js)
- Goal progress visualization
- Dark mode toggle

**Phase 3 Features:**
- Multi-page navigation
- Settings panel
- Push notifications
- Offline support (PWA)
- Photo upload for daily notes

---

**End of WebApp Specification**
