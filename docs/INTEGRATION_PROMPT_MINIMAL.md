# PiyuGuide Integration - Sidebar Behavior + Mobile Conversion (End-User Only)

**Version:** 1.0 (Minimal)  
**Date:** March 2026  
**Scope:** Sidebar Behavior + Socket.IO Real-time Notifications + Mobile Interface (Student/End-User Only)  
**Framework:** Flask + Bootstrap + PostgreSQL

---

## Quick Overview

This minimal prompt integrates **three features**:
1. **Responsive Sidebar Navigation Behavior** (collapsible sidebar, no page reload required)
2. **Real-time Notifications** (Socket.IO with Bootstrap UI)
3. **Mobile Interface Conversion** (responsive mobile menu - Student/End-User Side Only)

---

## Prerequisites

```bash
pip install flask-socketio python-socketio python-engineio eventlet
```

---

## Step 1: Extend Notification Model

**File: `app/models.py`**

Add to your existing User model:

```python
class User(UserMixin, db.Model):
    # ... existing columns ...
    is_online = db.Column(db.Boolean, default=False)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)

# NEW: Notification Model
class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text)
    notification_type = db.Column(db.String(50), default='info')  # info, success, warning, danger
    is_read = db.Column(db.Boolean, default=False)
    link = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='all_notifications')
```

Run migrations:
```bash
flask db migrate -m "Add notification system"
flask db upgrade
```

---

## Step 2: Extensions Setup

**File: `app/extensions.py`** (Create if doesn't exist)

```python
from flask_socketio import SocketIO

socketio = SocketIO(
    async_mode='eventlet',
    cors_allowed_origins='*'  # Restrict in production
)
```

---

## Step 3: Socket.IO Integration in App Factory

**File: `app/__init__.py`**

```python
from flask import Flask
from flask_socketio import join_room, leave_room
from flask_login import current_user
from app.extensions import socketio, db
from app.models import User, Notification

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize extensions
    db.init_app(app)
    socketio.init_app(app)
    
    # Register blueprints
    from app.auth import auth_bp
    from app.main import main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    
    # ===== Socket.IO Handlers =====
    @socketio.on('connect')
    def handle_connect():
        if current_user.is_authenticated:
            join_room(f'user_{current_user.id}')
            current_user.is_online = True
            db.session.commit()
            print(f'User {current_user.id} connected')
    
    @socketio.on('disconnect')
    def handle_disconnect():
        if current_user.is_authenticated:
            current_user.is_online = False
            db.session.commit()
            print(f'User {current_user.id} disconnected')
    
    @socketio.on('mark_notification_read')
    def mark_read(data):
        n = Notification.query.get(data.get('notification_id'))
        if n and n.user_id == current_user.id:
            n.is_read = True
            db.session.commit()
    
    # Template context processor
    @app.context_processor
    def inject_user_data():
        if current_user.is_authenticated:
            unread_count = Notification.query.filter_by(
                user_id=current_user.id, is_read=False
            ).count()
            return {'unread_notifications_count': unread_count}
        return {}
    
    with app.app_context():
        db.create_all()
    
    return app
```

---

## Step 4: Notification Utility

**File: `app/utils/notification_manager.py`** (New file)

```python
from flask_socketio import emit
from app.models import Notification, db
from app.extensions import socketio

class NotificationManager:
    @staticmethod
    def notify_user(user_id, title, message, notification_type='info', link=None):
        """Send real-time notification to user"""
        try:
            n = Notification(
                user_id=user_id,
                title=title,
                message=message,
                notification_type=notification_type,
                link=link
            )
            db.session.add(n)
            db.session.commit()
            
            # Emit real-time
            socketio.emit(
                'new_notification',
                {
                    'id': n.id,
                    'title': title,
                    'message': message,
                    'type': notification_type,
                    'link': link,
                    'created_at': n.created_at.isoformat(),
                },
                to=f'user_{user_id}',
                namespace='/'
            )
            return n
        except Exception as e:
            print(f'Error: {e}')
            return None
```

---

## Step 5: Template Integration Instructions

**Important:** Do NOT copy the template. Instead, integrate the sidebar behavior into your existing templates.

### For End-User (Student) Templates:

Add these elements to your existing student/end-user templates:

1. **In your `<head>` section**, add:
   ```html
   <!-- Custom CSS -->
   <link rel="stylesheet" href="{{ url_for('static', filename='css/sidebar.css') }}" />
   
   <!-- Socket.IO -->
   <script src="{{ url_for('static', filename='js/vendor/socket.io.min.js') }}"></script>
   ```

2. **In your navbar/header**, add a toggle button for mobile:
   ```html
   <button class="btn btn-link text-white d-lg-none me-2" id="mobileMenuBtn" type="button">
       <i class="fas fa-bars"></i>
   </button>
   ```

3. **Add notification bell** to your navbar (next to user dropdowns):
   ```html
   <div class="dropdown" id="notif-wrapper">
       <button class="btn btn-outline-light position-relative" id="notif-bell" type="button">
           <i class="fas fa-bell"></i>
           <span id="notif-badge" class="position-absolute top-0 start-100 translate-middle badge bg-danger rounded-pill {% if unread_notifications_count == 0 %}d-none{% endif %}">
               {{ unread_notifications_count }}
           </span>
       </button>
       
       <div id="notif-dropdown" class="dropdown-menu dropdown-menu-end shadow-lg p-0 d-none" style="width: 350px; max-height: 400px; overflow-y: auto;">
           <div class="dropdown-header bg-light fw-bold">
               <i class="fas fa-bell"></i> Notifications
           </div>
           <div id="notif-list">
               <!-- Notifications populated by JavaScript -->
           </div>
       </div>
   </div>
   ```

4. **For existing sidebar** in your student templates, add these mobile classes:
   ```html
   <!-- Your existing sidebar - add these classes -->
   <aside id="sidebar" class="bg-white border-end flex-shrink-0 overflow-y-auto d-none d-lg-block" style="width: 280px;">
       <!-- Your existing sidebar content -->
   </aside>
   
   <!-- Mobile Sidebar Overlay (add this) -->
   <div id="mobileSidebar" class="position-fixed top-0 start-0 bg-white border-end d-lg-none" style="width: 280px; height: 100%; z-index: 1000; transform: translateX(-100%); transition: transform 0.3s ease;">
       <button id="sidebarCloseBtn" class="btn-close m-3"></button>
       <!-- Copy your sidebar menu here for mobile -->
   </div>
   
   <!-- Mobile Overlay (add this) -->
   <div id="sidebarOverlay" class="position-fixed top-0 start-0 w-100 h-100 bg-dark bg-opacity-50 d-none d-lg-none" style="z-index: 999;"></div>
   ```

5. **At the bottom of your template**, add scripts:
   ```html
   <script src="{{ url_for('static', filename='js/sidebar.js') }}"></script>
   <script src="{{ url_for('static', filename='js/notifications.js') }}"></script>
   ```

### Admin/Staff Templates:
**Keep your existing admin templates unchanged.** Mobile conversion applies only to student/end-user facing pages.

---

## Step 6: Sidebar Behavior JavaScript

**File: `static/js/sidebar.js`**

This script handles:
- Mobile sidebar toggle (hamburger menu)
- Sidebar auto-hide on mobile overlay click
- Sidebar auto-hide on link navigation

```javascript
(function() {
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const mobileSidebar = document.getElementById('mobileSidebar');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    const sidebarCloseBtn = document.getElementById('sidebarCloseBtn');
    
    // Guard: Check if elements exist (for pages without sidebar)
    if (!mobileMenuBtn || !mobileSidebar) return;
    
    // Toggle mobile sidebar
    mobileMenuBtn.addEventListener('click', () => {
        mobileSidebar.style.transform = 'translateX(0)';
        sidebarOverlay.classList.remove('d-none');
    });
    
    // Close sidebar
    const closeSidebar = () => {
        mobileSidebar.style.transform = 'translateX(-100%)';
        sidebarOverlay.classList.add('d-none');
    };
    
    sidebarCloseBtn.addEventListener('click', closeSidebar);
    sidebarOverlay.addEventListener('click', closeSidebar);
    
    // Close on link click (mobile nav links get data-mobile-close-on-click attribute)
    document.querySelectorAll('[data-mobile-close-on-click]').forEach(link => {
        link.addEventListener('click', closeSidebar);
    });
})();
```

**To use with your existing sidebars:** Add `data-mobile-close-on-click` attribute to your sidebar links:
```html
<a href="/dashboard" class="nav-link" data-mobile-close-on-click>Dashboard</a>
```

---

## Step 7: Real-time Notifications JavaScript

**File: `static/js/notifications.js`**

```javascript
(function() {
    const socket = io();
    const notifBell = document.getElementById('notif-bell');
    const notifBadge = document.getElementById('notif-badge');
    const notifDropdown = document.getElementById('notif-dropdown');
    const notifList = document.getElementById('notif-list');
    
    // Toggle dropdown
    notifBell.addEventListener('click', (e) => {
        e.stopPropagation();
        notifDropdown.classList.toggle('d-none');
    });
    
    document.addEventListener('click', (e) => {
        if (!notifBell.contains(e.target) && !notifDropdown.contains(e.target)) {
            notifDropdown.classList.add('d-none');
        }
    });
    
    // Listen for new notifications
    socket.on('new_notification', (data) => {
        // Update badge
        let count = parseInt(notifBadge.textContent || '0');
        notifBadge.textContent = count + 1;
        notifBadge.classList.remove('d-none');
        
        // Create notification item
        const item = document.createElement('a');
        item.href = data.link || '#';
        item.className = 'dropdown-item border-bottom bg-light';
        item.dataset.notifId = data.id;
        item.innerHTML = `
            <div class="fw-bold small">${data.title}</div>
            <div class="text-muted small">${data.message}</div>
            <div class="text-muted small">${new Date().toLocaleString()}</div>
        `;
        
        // Add click handler to mark as read
        item.addEventListener('click', () => {
            socket.emit('mark_notification_read', { notification_id: data.id });
        });
        
        notifList.prepend(item);
    });
})();
```

---

## Step 8: CSS Styling for Sidebar Behavior

**File: `static/css/sidebar.css`**

Apply these styles to enhance sidebar navigation. These work with your existing sidebar structure:

```css
/* Sidebar navigation items */
.nav-item {
    padding: 0.75rem 1rem !important;
    color: #495057 !important;
    border-radius: 0.375rem;
    transition: all 0.2s ease;
}

.nav-item:hover {
    background-color: #f8f9fa !important;
    color: #0d6efd !important;
    transform: translateX(4px);
}

.nav-item.active {
    background-color: #0d6efd !important;
    color: white !important;
    font-weight: 600;
}

/* Mobile sidebar */
#mobileSidebar {
    box-shadow: 2px 0 8px rgba(0, 0, 0, 0.15);
}

/* Notification dropdown */
#notif-dropdown {
    min-width: 300px;
}

.dropdown-item {
    padding: 0.75rem 1rem;
    cursor: pointer;
    transition: background-color 0.2s ease;
}

.dropdown-item:hover {
    background-color: #f8f9fa;
}

.dropdown-item.unread {
    background-color: #e7f3ff;
}

/* Responsive adjustments */
@media (max-width: 991px) {
    /* Sidebar hides on mobile by default */
    #sidebar {
        display: none !important;
    }
    
    /* Mobile sidebar takes over */
    #mobileSidebar {
        display: block;
    }
}
```

---

## Step 9: Usage Example

In any of your routes, send a notification:

```python
from app.utils.notification_manager import NotificationManager

@main_bp.route('/submit', methods=['POST'])
@login_required
def submit():
    # Your code...
    
    # Notify admin
    admin_user = User.query.filter_by(role='admin').first()
    if admin_user:
        NotificationManager.notify_user(
            user_id=admin_user.id,
            title='New Submission',
            message=f'{current_user.first_name} submitted a form',
            notification_type='success',
            link='/admin/submissions'
        )
    
    return redirect(url_for('main.dashboard'))
```

---

## Step 10: Run Server

```bash
# Update run.py to use socketio
from app import create_app, socketio

if __name__ == '__main__':
    app = create_app()
    socketio.run(app, debug=True, host='127.0.0.1', port=5000)
```

---

## Testing

1. Start server: `python run.py`
2. Open app in browser
3. Open browser console (F12) → Check for "Connection established" message
4. In another terminal, trigger a notification:
   ```bash
   flask shell
   >>> from app import create_app, socketio
   >>> from app.utils.notification_manager import NotificationManager
   >>> app = create_app()
   >>> with app.app_context():
   ...     NotificationManager.notify_user(1, "Test", "This is a test", link="/dashboard")
   ```
5. Check browser - notification should appear in real-time

---

## Production Deployment (Gunicorn + Eventlet)

**File: `deploy/gunicorn.conf.py`**

```python
bind = "127.0.0.1:8000"
worker_class = "eventlet"
workers = 2
timeout = 180
```

**Nginx reverse proxy for WebSocket:**

```nginx
location /socket.io/ {
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_pass http://127.0.0.1:8000;
}
```

---

## Step 9: Checklist for Integration

### Core Setup
- [ ] Install `flask-socketio`, `python-socketio`, `eventlet`
- [ ] Add `Notification` model to `models.py`
- [ ] Create `extensions.py` with `socketio`
- [ ] Update `app/__init__.py` with Socket.IO handlers
- [ ] Create `notification_manager.py` utility
- [ ] Run migrations

### Front-End Integration (End-User/Student Templates Only)
- [ ] Add sidebar CSS link to your student templates: `<link rel="stylesheet" href="{{ url_for('static', filename='css/sidebar.css') }}" />`
- [ ] Add Socket.IO script: `<script src="{{ url_for('static', filename='js/vendor/socket.io.min.js') }}"></script>`
- [ ] Add mobile menu button to navbar: `<button class="btn btn-link text-white d-lg-none me-2" id="mobileMenuBtn" type="button"><i class="fas fa-bars"></i></button>`
- [ ] Add notification bell component to navbar
- [ ] Add mobile sidebar overlay components
- [ ] Add `data-mobile-close-on-click` attributes to sidebar links
- [ ] Create `static/js/sidebar.js`
- [ ] Create `static/js/notifications.js`
- [ ] Create `static/css/sidebar.css`

### Admin/Staff Templates (No Changes Required)
- [ ] Keep existing admin templates unchanged
- [ ] Mobile conversion NOT applied to admin side

### Testing & Deployment
- [ ] Test Socket.IO in browser console (F12)
- [ ] Test mobile sidebar toggle on student/end-user pages
- [ ] Test notification badge and dropdown
- [ ] Deploy with Gunicorn + eventlet (eventlet worker class)

---

## Implementation Notes

### Key Points
- **Mobile conversion is end-user/student side only** — Admin dashboards remain unchanged
- **Template Integration** — Don't replace your existing templates; add the sidebar behavior components to them
- **Backward Compatible** — Existing functionality is preserved; you're only adding new UI behaviors
- **Socket.IO Scope** — Notifications work across any route/template that includes the notification scripts

### Scope Limitation
To ensure mobile conversion only applies to end-user templates:
1. Add JS/CSS files only to student/end-user blueprints' base template
2. Admin templates inherit from their own admin base template
3. Keep admin sidebar as-is (desktop-only, no mobile toggle)

---

**Done! You now have sidebar behavior + real-time notifications + mobile interface conversion (end-user only) integrated into your Flask project without replacing templates.**
