"""Read Vitti Daily Mover packages written to Google Drive by the existing Gmail -> Apps Script import (script 5.2.x).

Drive layout (one folder per email, created by the Apps Script under the "TAR Daily Sources" folder):

    TAR Daily Sources/
      2026-11-17_1046_<gmailMessageId>_a1/
        SOURCE_INDEX.json          schema_version 4.0: email headers incl. DKIM result, Daily Mover sha256, file list
        AWAITING_VERIFICATION      status marker
        DAILY_MOVER/<TICKER>-<YYYY-MM-DD>-draft.pdf
        EXTRACTED/today/*.pdf      the company's own ASX announcements of the day, supplied by Vitti in its ZIP
        EXTRACTED/history/*.pdf    older announcements (not used by the generator)
        ORIGINAL_ZIP/

The generator only READS Drive (scope drive.readonly). LocalSource reads the same structure from a local directory so
the whole pipeline can be tested offline: <dir>/SOURCE_INDEX.json, <dir>/daily_mover.pdf, optional <dir>/today/*.pdf.
"""
import glob, json, os, re, tempfile

from .common import GenError, sha256_file

FOLDER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_\d{4}_[0-9a-f]{8,}_a\d+$")
MAX_SUPPORT_BYTES = 15 * 1024 * 1024
MAX_SUPPORT_FILES = 6

# Package states written by the Apps Script import. A package is used only when the import has FINISHED with it.
READY_STATES = {"AWAITING_VERIFICATION", "VERIFIED", "READY"}
# NOT_READY is accepted only for this known benign shape: Vitti sent PDF links instead of a ZIP, so there are no
# supporting announcements, but the Daily Mover itself was saved and size-verified.
NOT_READY_OK_SHAPES = {"PDF_LINKS_NO_ZIP"}


def package_complete(idx):
    """(True, "") when the import finished writing this package and its Daily Mover; else (False, reason code).
    PROCESSING / unknown states, a missing or unverified Daily Mover, or a NOT_READY package for any other reason
    are never used: an incomplete Drive package can never reach publication. Mirrored in apps-script/TarDispatch.gs."""
    st = str(idx.get("status") or "").upper()
    dm = idx.get("daily_mover") or {}
    if st == "NOT_READY":
        if idx.get("import_shape") not in NOT_READY_OK_SHAPES:
            return False, "PACKAGE_NOT_READY"
    elif st not in READY_STATES:
        return False, "PACKAGE_INCOMPLETE"
    if dm.get("status") != "found" or not dm.get("drive_file_id"):
        return False, "PACKAGE_NO_DAILY_MOVER"
    if dm.get("saved") is False or dm.get("size_verified") is False:
        return False, "PACKAGE_DAILY_MOVER_UNVERIFIED"
    return True, ""


class Package:
    def __init__(self, package_id, index, daily_mover_path, today_docs, folder_id=None, created=None):
        self.package_id = package_id
        self.index = index
        self.daily_mover_path = daily_mover_path
        self.today_docs = today_docs            # [(name, local_path)]
        self.folder_id = folder_id
        self.created = created

    def __repr__(self):
        return f"Package({self.package_id})"


class LocalSource:
    """A directory per package (offline tests and manual reruns)."""
    def __init__(self, path):
        self.path = path

    def packages_for(self, d):
        dirs = [self.path] if os.path.isfile(os.path.join(self.path, "SOURCE_INDEX.json")) else sorted(glob.glob(os.path.join(self.path, "*")))
        out = []
        for p in dirs:
            ip = os.path.join(p, "SOURCE_INDEX.json")
            if not os.path.isfile(ip):
                continue
            idx = json.load(open(ip, encoding="utf-8"))
            if not str(idx.get("package_id", "")).startswith(d.isoformat()):
                continue
            if not package_complete(idx)[0]:
                continue
            today = [(os.path.basename(f), f) for f in sorted(glob.glob(os.path.join(p, "today", "*.pdf")))]
            out.append(Package(idx["package_id"], idx, os.path.join(p, "daily_mover.pdf"), today[:MAX_SUPPORT_FILES],
                               folder_id=(idx.get("drive") or {}).get("package_folder_id"), created=idx.get("processed_at")))
        return sorted(out, key=lambda x: x.created or "", reverse=True)


class DriveSource:
    """Google Drive v3 REST, read-only, authenticated as a service account the "TAR Daily Sources" folder is shared with.

    Secret GOOGLE_SERVICE_ACCOUNT_JSON holds the key file content. Nothing is ever written to Drive."""
    API = "https://www.googleapis.com/drive/v3/files"
    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

    def __init__(self, root_folder_id, key_json, workdir=None):
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as e:  # pragma: no cover - dependency is installed by the workflow
            raise GenError("DEPENDENCY", f"google-auth is not installed ({e})")
        try:
            info = json.loads(key_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=self.SCOPES)
        except Exception as e:
            raise GenError("DRIVE_AUTH", f"GOOGLE_SERVICE_ACCOUNT_JSON is not a valid service account key ({type(e).__name__})")
        self.http = AuthorizedSession(creds)
        self.root = root_folder_id
        self.workdir = workdir or tempfile.mkdtemp(prefix="tar_pkg_")

    def _get(self, url, **params):
        for attempt in range(4):
            try:
                r = self.http.get(url, params=params, timeout=60)
            except Exception as e:
                if attempt == 3:
                    raise GenError("DRIVE_UNREACHABLE", f"Drive request failed ({type(e).__name__})", transient=True)
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                import time; time.sleep(2 ** attempt * 3)
                continue
            if r.status_code in (401, 403):
                raise GenError("DRIVE_FORBIDDEN", f"Drive answered HTTP {r.status_code}: share the TAR Daily Sources folder with the service account (Viewer)")
            if r.status_code == 404:
                raise GenError("DRIVE_NOT_FOUND", "Drive file or folder not found (check vitti_generator.drive_root_folder_id)")
            if r.status_code != 200:
                raise GenError("DRIVE_HTTP", f"Drive answered HTTP {r.status_code}", transient=r.status_code >= 500)
            return r
        raise GenError("DRIVE_UNREACHABLE", "Drive request failed", transient=True)

    def _list(self, q, fields="files(id,name,mimeType,createdTime,size)"):
        out, token = [], None
        while True:
            params = dict(q=q, fields=f"nextPageToken,{fields}", pageSize=200, orderBy="createdTime desc",
                          supportsAllDrives="true", includeItemsFromAllDrives="true")
            if token:
                params["pageToken"] = token
            j = self._get(self.API, **params).json()
            out += j.get("files", [])
            token = j.get("nextPageToken")
            if not token:
                return out

    def _download(self, file_id, dest, max_bytes=MAX_SUPPORT_BYTES):
        r = self._get(f"{self.API}/{file_id}", alt="media", supportsAllDrives="true")
        if len(r.content) > max_bytes:
            raise GenError("DRIVE_FILE_TOO_LARGE", f"file {file_id} is larger than {max_bytes} bytes")
        with open(dest, "wb") as f:
            f.write(r.content)
        return dest

    def ping(self):
        """Read-only connection test: the root folder is visible to the service account."""
        j = self._get(f"{self.API}/{self.root}", fields="id,name,mimeType", supportsAllDrives="true").json()
        if j.get("mimeType") != "application/vnd.google-apps.folder":
            raise GenError("DRIVE_ROOT", "vitti_generator.drive_root_folder_id is not a folder")
        return j["name"]

    def packages_for(self, d):
        q = (f"'{self.root}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder' "
             f"and name contains '{d.isoformat()}_'")
        folders = [f for f in self._list(q) if FOLDER_RE.match(f["name"]) and f["name"].startswith(d.isoformat())]
        out = []
        for f in folders:  # newest first
            idx_files = self._list(f"'{f['id']}' in parents and trashed=false and name='SOURCE_INDEX.json'")
            if not idx_files:
                continue  # still being written by the Apps Script; a later run picks it up
            pdir = os.path.join(self.workdir, f["name"])
            os.makedirs(os.path.join(pdir, "today"), exist_ok=True)
            ip = self._download(idx_files[0]["id"], os.path.join(pdir, "SOURCE_INDEX.json"), max_bytes=2 * 1024 * 1024)
            try:
                idx = json.load(open(ip, encoding="utf-8"))
            except ValueError:
                continue
            if not package_complete(idx)[0]:
                continue  # import still running or package unusable; a later run looks again
            dm = idx["daily_mover"]
            dmp = self._download(dm["drive_file_id"], os.path.join(pdir, "daily_mover.pdf"), max_bytes=5 * 1024 * 1024)
            today = []
            for fe in idx.get("files") or []:
                rp = fe.get("relative_path") or ""
                if rp.startswith("today/") and fe.get("is_pdf") and fe.get("drive_file_id") and (fe.get("size_bytes") or 0) <= MAX_SUPPORT_BYTES:
                    if len(today) >= MAX_SUPPORT_FILES:
                        break
                    lp = os.path.join(pdir, "today", f"{len(today):02d}.pdf")
                    self._download(fe["drive_file_id"], lp)
                    if fe.get("sha256") and sha256_file(lp) != fe["sha256"]:
                        raise GenError("SUPPORT_HASH", f"supporting file {fe.get('name')} does not match its SOURCE_INDEX sha256")
                    today.append((fe.get("name") or rp, lp))
            out.append(Package(idx.get("package_id") or f["name"], idx, dmp, today, folder_id=f["id"], created=f.get("createdTime")))
        return out


def make_source(cfg_gen, local_dir=None):
    if local_dir:
        return LocalSource(local_dir)
    key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not key:
        raise GenError("DRIVE_SECRET_MISSING", "GOOGLE_SERVICE_ACCOUNT_JSON secret is not set")
    return DriveSource(cfg_gen["drive_root_folder_id"], key)
