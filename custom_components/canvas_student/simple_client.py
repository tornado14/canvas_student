
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from aiohttp import ClientSession
from yarl import URL
from .const import *

_LOGGER = logging.getLogger(__name__)

class CanvasApiError(Exception): pass

class CanvasClient:
    def __init__(self, base_url: str, access_token: str, session: Optional[ClientSession] = None) -> None:
        self._base = base_url.rstrip("/"); self._token = access_token.strip() if access_token else access_token; self._session = session
    @property
    def base_url(self) -> str: return self._base
    @property
    def _headers(self) -> Dict[str, str]: return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    async def _get_all_pages(self, path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        url = URL(self._base + path); params = params or {}; items: List[Dict[str, Any]] = []; page = 1
        while True:
            _LOGGER.debug("Canvas GET %s params=%s page=%s", url, params, page)
            async with self._session.get(url, headers=self._headers, params=params) as resp:
                if resp.status == 401:
                    txt = await resp.text()
                    red = self._token[:4] + "…" + self._token[-4:] if self._token else "None"
                    _LOGGER.error("Canvas 401 Unauthorized @ %s (token=%s). Body: %s", self._base, red, txt)
                    raise CanvasApiError(f"401 Unauthorized at {self._base}: {txt}")
                if resp.status >= 400:
                    txt = await resp.text(); _LOGGER.error("Canvas error %s @ %s: %s", resp.status, self._base, txt); raise CanvasApiError(f"{resp.status}: {txt}")
                data = await resp.json()
                if isinstance(data, list): items.extend(data)
                else: items.append(data)
                link = resp.headers.get("Link") or resp.headers.get("link")
                if not link or 'rel="next"' not in link: break
                next_url = None
                for part in link.split(","):
                    if 'rel="next"' in part:
                        start = part.find("<") + 1; end = part.find(">"); next_url = part[start:end]; break
                if not next_url: break
                url = URL(next_url); params = {}; page += 1
        return items

    async def list_courses(self) -> List[Dict[str, Any]]:
        return await self._get_all_pages(PATH_COURSES, {"enrollment_state": "active", "include[]": ["term"], "per_page": 50})

    async def list_assignments(self, course_id: str, bucket: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"order_by": "due_at", "per_page": 50}
        if bucket: params["bucket"] = bucket
        return await self._get_all_pages(PATH_ASSIGNMENTS.format(course_id=course_id), params)

# NEW: list submissions for the current user in a course
    async def list_submissions_self(
        self,
        course_id: str,
        workflow_state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Returns submissions for the current user in a course.

        Each item is the raw Canvas submission dict, optionally with `assignment`
        included if Canvas provides it.
        """
        params: Dict[str, Any] = {
            "student_ids[]": "self",
            "include[]": ["assignment"],
            "per_page": 50,
        }
        if workflow_state:
            params["workflow_state"] = workflow_state

        return await self._get_all_pages(
            PATH_STUDENT_SUBMISSIONS_SELF.format(course_id=course_id),
            params,
        )

    async def get_submission_self(self, course_id: str, assignment_id: str) -> Dict[str, Any]:
        url = URL(self._base + PATH_SUBMISSIONS_SELF.format(course_id=course_id, assignment_id=assignment_id))
        async with self._session.get(url, headers=self._headers) as resp:
            if resp.status >= 400: raise CanvasApiError(f"{resp.status}: " + await resp.text())
            return await resp.json()

    async def get_users_self(self) -> Dict[str, Any]:
        url = URL(self._base + PATH_USERS_SELF)
        async with self._session.get(url, headers=self._headers) as resp:
            if resp.status >= 400: raise CanvasApiError(f"{resp.status}: " + await resp.text())
            return await resp.json()

    async def get_announcements(self, context_codes: List[str], start_date, end_date) -> List[Dict[str, Any]]:
        params = {"context_codes[]": context_codes, "start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "active_only": "true", "per_page": 50}
        return await self._get_all_pages(PATH_ANNOUNCEMENTS, params)

    async def list_enrollments(self, course_id: str) -> List[Dict[str, Any]]:
        return await self._get_all_pages(PATH_ENROLLMENTS.format(course_id=course_id), {"type[]": ["StudentEnrollment"], "user_id": "self", "per_page": 50})
