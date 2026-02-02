"""
Supabase client configuration
"""
from typing import Optional
from supabase import create_client, Client
from functools import lru_cache

from app.core.config import settings


@lru_cache()
def get_supabase_client() -> Client:
    """Get Supabase client instance"""
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise ValueError("Supabase configuration missing")
    
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_ANON_KEY
    )


@lru_cache()
def get_supabase_admin_client() -> Client:
    """Get Supabase admin client (bypasses RLS)"""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise ValueError("Supabase admin configuration missing")
    
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_KEY
    )


class SupabaseDB:
    """Supabase database operations wrapper"""
    
    def __init__(self, client: Optional[Client] = None):
        self._client = client
    
    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = get_supabase_client()
        return self._client
    
    async def query(
        self,
        table: str,
        select: str = "*",
        filters: dict = None
    ):
        """Execute a query with filters"""
        query = self.client.table(table).select(select)
        
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)
        
        return query.execute()
    
    async def insert(
        self,
        table: str,
        data: dict
    ):
        """Insert a record"""
        return self.client.table(table).insert(data).execute()
    
    async def update(
        self,
        table: str,
        data: dict,
        filters: dict
    ):
        """Update records matching filters"""
        query = self.client.table(table).update(data)
        
        for key, value in filters.items():
            query = query.eq(key, value)
        
        return query.execute()


# Default instance
db = SupabaseDB()
