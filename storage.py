import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
import threading

class BarkStorage:
    """Compact SQLite-based storage for Bark Discord bot"""
    
    def __init__(self, db_path: str = "bark_data.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_database()
    
    def _init_database(self):
        """Initialize database with required tables"""
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            
            # Servers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS servers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT,
                    member_count INTEGER DEFAULT 0,
                    created_at TEXT,
                    first_seen TEXT,
                    last_seen TEXT,
                    data TEXT DEFAULT '{}'
                )
            """)
            
            # Members table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    id TEXT,
                    server_id TEXT,
                    username TEXT,
                    display_name TEXT,
                    is_bot BOOLEAN DEFAULT 0,
                    joined_at TEXT,
                    first_seen TEXT,
                    last_seen TEXT,
                    data TEXT DEFAULT '{}',
                    PRIMARY KEY (id, server_id),
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE
                )
            """)
            
            # Key-value storage for modules
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS module_data (
                    module_name TEXT,
                    server_id TEXT,
                    key TEXT,
                    value TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (module_name, server_id, key)
                )
            """)
            
            # Analytics/events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT,
                    event_type TEXT,
                    data TEXT,
                    timestamp TEXT,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE
                )
            """)
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_members_server ON members(server_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_server ON events(server_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_module_data_lookup ON module_data(module_name, server_id)")
            
            conn.commit()
            conn.close()
    
    def _get_connection(self):
        """Get database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    # Server operations
    def upsert_server(self, server_id: str, name: str, owner_id: str = None, 
                     member_count: int = 0, created_at: str = None, **kwargs) -> bool:
        """Insert or update server information"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            now = datetime.utcnow().isoformat()
            data = json.dumps(kwargs)
            
            cursor.execute("""
                INSERT INTO servers (id, name, owner_id, member_count, created_at, first_seen, last_seen, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    owner_id = excluded.owner_id,
                    member_count = excluded.member_count,
                    last_seen = excluded.last_seen,
                    data = excluded.data
            """, (server_id, name, owner_id, member_count, created_at, now, now, data))
            
            conn.commit()
            conn.close()
            return True
    
    def get_server(self, server_id: str) -> Optional[Dict]:
        """Get server information"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                result = dict(row)
                result['data'] = json.loads(result['data'])
                return result
            return None
    
    def get_all_servers(self) -> List[Dict]:
        """Get all servers"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM servers ORDER BY last_seen DESC")
            rows = cursor.fetchall()
            conn.close()
            
            result = []
            for row in rows:
                server = dict(row)
                server['data'] = json.loads(server['data'])
                result.append(server)
            return result
    
    # Member operations
    def upsert_member(self, member_id: str, server_id: str, username: str,
                     display_name: str = None, is_bot: bool = False,
                     joined_at: str = None, **kwargs) -> bool:
        """Insert or update member information"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            now = datetime.utcnow().isoformat()
            data = json.dumps(kwargs)
            
            cursor.execute("""
                INSERT INTO members (id, server_id, username, display_name, is_bot, joined_at, first_seen, last_seen, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id, server_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name,
                    is_bot = excluded.is_bot,
                    joined_at = excluded.joined_at,
                    last_seen = excluded.last_seen,
                    data = excluded.data
            """, (member_id, server_id, username, display_name, is_bot, joined_at, now, now, data))
            
            conn.commit()
            conn.close()
            return True
    
    def get_member(self, member_id: str, server_id: str) -> Optional[Dict]:
        """Get member information"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM members WHERE id = ? AND server_id = ?", 
                          (member_id, server_id))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                result = dict(row)
                result['data'] = json.loads(result['data'])
                return result
            return None
    
    def get_server_members(self, server_id: str) -> List[Dict]:
        """Get all members for a server"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM members WHERE server_id = ? ORDER BY username", 
                          (server_id,))
            rows = cursor.fetchall()
            conn.close()
            
            result = []
            for row in rows:
                member = dict(row)
                member['data'] = json.loads(member['data'])
                result.append(member)
            return result
    
    # Module data operations
    def set_module_data(self, module_name: str, server_id: str, key: str, value: Any) -> bool:
        """Store module-specific data"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            now = datetime.utcnow().isoformat()
            json_value = json.dumps(value)
            
            cursor.execute("""
                INSERT INTO module_data (module_name, server_id, key, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(module_name, server_id, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
            """, (module_name, server_id, key, json_value, now))
            
            conn.commit()
            conn.close()
            return True
    
    def get_module_data(self, module_name: str, server_id: str, key: str, default=None) -> Any:
        """Get module-specific data"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT value FROM module_data 
                WHERE module_name = ? AND server_id = ? AND key = ?
            """, (module_name, server_id, key))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return json.loads(row['value'])
            return default
    
    def get_all_module_data(self, module_name: str, server_id: str) -> Dict:
        """Get all data for a module in a server"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT key, value FROM module_data 
                WHERE module_name = ? AND server_id = ?
            """, (module_name, server_id))
            
            rows = cursor.fetchall()
            conn.close()
            
            result = {}
            for row in rows:
                result[row['key']] = json.loads(row['value'])
            return result
    
    def delete_module_data(self, module_name: str, server_id: str, key: str = None) -> bool:
        """Delete module data (specific key or all for module/server)"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if key:
                cursor.execute("""
                    DELETE FROM module_data 
                    WHERE module_name = ? AND server_id = ? AND key = ?
                """, (module_name, server_id, key))
            else:
                cursor.execute("""
                    DELETE FROM module_data 
                    WHERE module_name = ? AND server_id = ?
                """, (module_name, server_id))
            
            conn.commit()
            conn.close()
            return True
    
    # Event logging
    def log_event(self, server_id: str, event_type: str, data: Dict = None) -> bool:
        """Log an event"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            now = datetime.utcnow().isoformat()
            json_data = json.dumps(data or {})
            
            cursor.execute("""
                INSERT INTO events (server_id, event_type, data, timestamp)
                VALUES (?, ?, ?, ?)
            """, (server_id, event_type, json_data, now))
            
            conn.commit()
            conn.close()
            return True
    
    def get_events(self, server_id: str = None, event_type: str = None, 
                   limit: int = 100) -> List[Dict]:
        """Get events with optional filtering"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            query = "SELECT * FROM events WHERE 1=1"
            params = []
            
            if server_id:
                query += " AND server_id = ?"
                params.append(server_id)
            
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            
            result = []
            for row in rows:
                event = dict(row)
                event['data'] = json.loads(event['data'])
                result.append(event)
            return result
    
    # Statistics and analytics
    def get_server_stats(self, server_id: str) -> Dict:
        """Get comprehensive server statistics"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Basic server info
            cursor.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
            server = cursor.fetchone()
            
            if not server:
                conn.close()
                return {}
            
            # Member statistics
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_members,
                    SUM(CASE WHEN is_bot = 1 THEN 1 ELSE 0 END) as bot_count,
                    SUM(CASE WHEN is_bot = 0 THEN 1 ELSE 0 END) as human_count
                FROM members WHERE server_id = ?
            """, (server_id,))
            member_stats = cursor.fetchone()
            
            # Recent activity
            cursor.execute("""
                SELECT event_type, COUNT(*) as count
                FROM events 
                WHERE server_id = ? AND timestamp > datetime('now', '-7 days')
                GROUP BY event_type
                ORDER BY count DESC
            """, (server_id,))
            activity = cursor.fetchall()
            
            conn.close()
            
            return {
                'server': dict(server),
                'members': dict(member_stats) if member_stats else {},
                'recent_activity': [dict(row) for row in activity]
            }
    
    # Cleanup and maintenance
    def cleanup_old_events(self, days: int = 30) -> int:
        """Remove events older than specified days"""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                DELETE FROM events 
                WHERE timestamp < datetime('now', '-{} days')
            """.format(days))
            
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            return deleted
    
    def vacuum(self):
        """Optimize database"""
        with self.lock:
            conn = self._get_connection()
            conn.execute("VACUUM")
            conn.close()
    
    def close(self):
        """Close database (for cleanup)"""
        pass  # SQLite connections are per-thread, so nothing to close