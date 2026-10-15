"""Site scraping, planning and the parallel download pipeline. No GUI code in here."""

from __future__ import annotations

import html
import copy
import os
import queue
import re
import shutil
import threading
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import Manager
from pathlib import Path

import requests

from builders import build_file

NO_VOLUME = 0


class SiteError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Chapter:
    number: float
    volume: int  # NO_VOLUME when the site does not say
    url: str


@dataclass
class Group:
    """The chapters that end up in one output file."""
    label: str
    chapters: list[Chapter]


@dataclass
class MangaInfo:
    title: str
    chapters: list[Chapter]
    cover: bytes | None = None
    status: str = ""
    genres: list[str] = field(default_factory=list)


class RateLimiter:
    """Spaces out request starts across all threads, so more workers never means more requests per second."""

    def __init__(self, delay: float):
        self.delay = delay
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.delay
        time.sleep(start - now)


class SharedRateLimiter:
    """The same as RateLimiter, but shared between processes through a multiprocessing manager."""

    def __init__(self, delay: float, manager):
        self.delay = delay
        self._lock = manager.Lock()
        self._next = manager.Value("d", 0.0)

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next.value)
            self._next.value = start + self.delay
        time.sleep(max(0.0, start - now))


# --------------------------------------------------------------------------- sites


class FanFox:
    name = "fanfox.net"
    example = "https://fanfox.net/manga/<title>/"
    url_re = re.compile(r"(?:fanfox\.net|mangafox\.\w+)/manga/([a-z0-9_]+)", re.I)
    _title_re = re.compile(r'class="detail-info-right-title-font">([^<]+)<')
    _status_re = re.compile(r'class="detail-info-right-title-tip">([^<]+)<')
    _genres_re = re.compile(r'<p class="detail-info-right-tag-list">(.*?)</p>', re.S)
    _cover_re = re.compile(r'<img class="detail-info-cover-img" src="([^"]+)"')
    _image_re = re.compile(r'data-original="([^"]+)"')
    _user_agent = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/129.0 Mobile Safari/537.36")

    def __init__(self, url: str, limiter: RateLimiter):
        self.slug = self.url_re.search(url).group(1).lower()
        self.limiter = limiter
        self._local = threading.local()  # one HTTP session per thread
        # Only this title's own links; the page also links to chapters of other manga.
        self._chapter_re = re.compile(
            rf'href="(/manga/{re.escape(self.slug)}/(?:v([^/"]+)/)?c([\d.]+)/1\.html)"', re.I)

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        del state["_local"]  # sessions can't be sent to another process; each one makes its own
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._local = threading.local()

    def with_limiter(self, limiter) -> FanFox:
        clone = copy.copy(self)
        clone.limiter = limiter
        return clone

    @property
    def _http(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            s = requests.Session()
            s.headers["User-Agent"] = self._user_agent
            s.cookies.set("isAdult", "1", domain=".fanfox.net")
            self._local.session = s
        return self._local.session

    def _get(self, url: str, referer: str = "https://fanfox.net/", retries: int = 3,
             method: str = "GET") -> requests.Response:
        last = "unknown error"
        for attempt in range(retries):
            self.limiter.wait()
            if attempt:
                time.sleep(attempt * 2)  # back off a little more after each failure
            try:
                resp = self._http.request(method, url, headers={"Referer": referer}, timeout=30)
                if resp.status_code == 200:
                    return resp
                last = f"HTTP {resp.status_code}"
                if resp.status_code in (403, 404):
                    break
            except requests.RequestException as e:
                last = type(e).__name__
        raise SiteError(f"Could not fetch {url}: {last}")

    @property
    def key(self) -> str:
        """Identifies the title across runs, e.g. for download history."""
        return f"{self.name}:{self.slug}"

    @property
    def title_url(self) -> str:
        return f"https://fanfox.net/manga/{self.slug}/"

    def info(self, with_cover: bool = True) -> MangaInfo:
        page = self._get(self.title_url).text
        title = self._title_re.search(page)
        found = {}
        for path, vol, num in self._chapter_re.findall(page):
            found[path] = Chapter(float(num), int(vol) if vol.isdigit() else NO_VOLUME, path)
        status = self._status_re.search(page)
        genres = self._genres_re.search(page)
        info = MangaInfo(
            title=html.unescape(title.group(1)).strip() if title else self.slug.replace("_", " ").title(),
            chapters=sorted(found.values(), key=lambda c: (c.number, c.url)),
            status=status.group(1).strip() if status else "",
            genres=re.findall(r'title="([^"]+)"', genres.group(1)) if genres else [],
        )
        cover = self._cover_re.search(page) if with_cover else None
        if cover:
            try:
                info.cover = self._get(html.unescape(cover.group(1)), retries=1).content
            except SiteError:
                pass  # a missing cover is not worth failing over
        return info

    def page_urls(self, chapter: Chapter) -> list[str]:
        # The mobile "roll" reader lists every page of a chapter in one document.
        roll = "https://m.fanfox.net" + chapter.url.replace("/manga/", "/roll_manga/", 1)
        urls = [html.unescape(u) for u in self._image_re.findall(self._get(roll).text)]
        if not urls:
            raise SiteError(f"No pages found for chapter {fmt_num(chapter.number)}")
        return ["https:" + u if u.startswith("//") else u for u in urls]

    def image_size(self, url: str) -> int | None:
        """Size of an image in bytes, asking only for its headers."""
        resp = self._get(url, referer="https://m.fanfox.net/", retries=1, method="HEAD")
        length = resp.headers.get("content-length", "")
        return int(length) if length.isdigit() else None

    def image(self, url: str) -> bytes:
        resp = self._get(url, referer="https://m.fanfox.net/")
        if not resp.headers.get("content-type", "").startswith("image/"):
            raise SiteError(f"Not an image: {url}")
        return resp.content


SITES = [FanFox]


def site_for(url: str):
    return next((s for s in SITES if s.url_re.search(url)), None)


# --------------------------------------------------------------------------- planning


def fmt_num(n: float) -> str:
    return f"{n:g}"


def chapter_span(chapters: list[Chapter]) -> str:
    first, last = chapters[0].number, chapters[-1].number
    return fmt_num(first) if first == last else f"{fmt_num(first)}-{fmt_num(last)}"


def make_groups(chapters: list[Chapter], per_file: int) -> list[Group]:
    """One group per volume; chapters without a volume are split into files of per_file chapters."""
    by_volume: dict[int, list[Chapter]] = {}
    for ch in chapters:
        by_volume.setdefault(ch.volume, []).append(ch)
    loose = by_volume.pop(NO_VOLUME, [])
    groups = [Group(f"Vol. {vol:02d}", chs) for vol, chs in sorted(by_volume.items())]
    for i in range(0, len(loose), per_file):
        part = loose[i:i + per_file]
        groups.append(Group(f"Ch. {chapter_span(part)}", part))
    return groups


def estimate_chapter_bytes(site, chapters: list[Chapter], samples: int = 3, per_chapter: int = 5) -> float | None:
    """Average download size of a chapter, from a few chapters spread across the title.

    For each sampled chapter it reads the page list and the sizes of a few pages spread through
    it, then scales up by the page count. About samples * (1 + per_chapter) small requests.
    """
    if not chapters:
        return None
    picks = sorted({round(i * (len(chapters) - 1) / max(1, samples - 1)) for i in range(samples)})
    totals = []
    for i in picks:
        try:
            urls = site.page_urls(chapters[i])
            spread = sorted({round(k * (len(urls) - 1) / max(1, per_chapter - 1))
                             for k in range(min(per_chapter, len(urls)))})
            sizes = [n for n in (site.image_size(urls[k]) for k in spread) if n]
        except SiteError:
            continue
        if sizes:
            totals.append(sum(sizes) / len(sizes) * len(urls))
    return sum(totals) / len(totals) if totals else None


def safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "manga"


# --------------------------------------------------------------------------- download

EXT_BY_MAGIC = [(b"\xff\xd8", ".jpg"), (b"\x89PNG", ".png"), (b"GIF8", ".gif"), (b"RIFF", ".webp")]


def image_ext(data: bytes) -> str:
    for magic, ext in EXT_BY_MAGIC:
        if data.startswith(magic):
            return ext
    return ".avif" if data[4:12] in (b"ftypavif", b"ftypavis") else ".jpg"


def download_group(site, group: Group, group_dir: Path, cancel: threading.Event,
                   on_progress: Callable[[float, str], None]) -> list[Path]:
    """Download every page of a group into group_dir; already-downloaded chapters are skipped."""
    n = len(group.chapters)
    for done, ch in enumerate(group.chapters):
        ch_dir = group_dir / f"ch_{ch.number:08.2f}"
        if (ch_dir / ".done").exists():
            continue
        ch_dir.mkdir(parents=True, exist_ok=True)
        if cancel.is_set():
            raise Cancelled
        urls = site.page_urls(ch)
        for i, url in enumerate(urls, 1):
            if cancel.is_set():
                raise Cancelled
            if not list(ch_dir.glob(f"{i:04d}.*")):
                data = site.image(url)
                (ch_dir / f"{i:04d}{image_ext(data)}").write_bytes(data)
            on_progress((done + i / len(urls)) / n, f"Ch. {fmt_num(ch.number)}  ·  page {i}/{len(urls)}")
        (ch_dir / ".done").touch()
    return sorted(p for p in group_dir.glob("ch_*/*") if p.name != ".done" and ".conv." not in p.name)


# Job states reported to on_status.
QUEUED, DOWNLOADING, BUILDING, DONE, SKIPPED, FAILED, CANCELLED = (
    "Queued", "Downloading", "Building", "Done", "Already exists", "Failed", "Cancelled")

# How download workers run (a setting).
THREADS, PROCESSES = "threads", "processes"


def make_file(site, index: int, group: Group, fmt: str, title: str, book_dir: Path, work_dir: Path,
              keep_tmp: bool, cancel, report: Callable[[int, str, float, str], None],
              build: Callable[..., Path]) -> bool:
    """Download one group and build its file. Returns False if it failed."""
    name = safe_name(f"{title} - {group.label}")
    target = book_dir / (name if fmt == "images" else f"{name}.{fmt}")
    try:
        if cancel.is_set():
            raise Cancelled
        if target.exists():
            report(index, SKIPPED, 1.0, str(target))
            return True
        group_dir = work_dir / safe_name(group.label)
        images = download_group(site, group, group_dir, cancel,
                                lambda frac, msg: report(index, DOWNLOADING, frac, msg))
        report(index, BUILDING, 1.0, f"Making {fmt.upper()}")
        build(fmt, images, target, f"{title} - {group.label}")
        if not keep_tmp:
            shutil.rmtree(group_dir, ignore_errors=True)
        report(index, DONE, 1.0, str(target))
        return True
    except Cancelled:
        report(index, CANCELLED, 0.0, "")
        return True
    except Exception as e:  # report and carry on with the other files
        report(index, FAILED, 0.0, str(e))
        return False


def _process_job(site, index, group, fmt, title, book_dir, work_dir, keep_tmp, cancel, events) -> bool:
    """Entry point for process mode: runs in a worker process and reports through a queue."""
    return make_file(site, index, group, fmt, title, book_dir, work_dir, keep_tmp, cancel,
                     lambda *status: events.put(status), build_file)


def run_jobs(site, title: str, groups: list[Group], fmt: str, book_dir: Path, work_dir: Path,
             keep_tmp: bool, workers: int, cancel: threading.Event,
             on_status: Callable[[int, str, float, str], None], mode: str = THREADS) -> list[int]:
    """Download and build each group, `workers` at a time. Returns the indexes that failed.

    THREADS: downloads run on threads (the GIL is released while waiting on the network) and
    building runs in a process pool, so CPU-heavy builds use several cores.
    PROCESSES: each file is downloaded and built in its own worker process.
    Either way all workers share one request rate limit.
    """
    book_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, workers)
    if mode == PROCESSES:
        ok = _run_in_processes(site, title, groups, fmt, book_dir, work_dir, keep_tmp, workers, cancel, on_status)
    else:
        with ProcessPoolExecutor(max_workers=min(workers, os.cpu_count() or 1)) as builders, \
                ThreadPoolExecutor(max_workers=workers) as pool:
            def build(*args) -> Path:
                return builders.submit(build_file, *args).result()

            futures = [pool.submit(make_file, site, i, g, fmt, title, book_dir, work_dir, keep_tmp,
                                   cancel, on_status, build) for i, g in enumerate(groups)]
            ok = [f.result() for f in futures]

    failed = [i for i, good in enumerate(ok) if not good]
    if not keep_tmp and not failed and not cancel.is_set():
        shutil.rmtree(work_dir, ignore_errors=True)
        parent = work_dir.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    return failed


def _run_in_processes(site, title, groups, fmt, book_dir, work_dir, keep_tmp, workers, cancel,
                      on_status) -> list[bool]:
    with Manager() as manager:
        shared_cancel = manager.Event()
        events = manager.Queue()
        remote_site = site.with_limiter(SharedRateLimiter(site.limiter.delay, manager))
        stop = threading.Event()

        def relay() -> None:
            """Forward progress from the workers to on_status, and the cancel button to the workers."""
            while not stop.is_set() or not events.empty():
                if cancel.is_set() and not shared_cancel.is_set():
                    shared_cancel.set()
                try:
                    on_status(*events.get(timeout=0.1))
                except queue.Empty:
                    pass

        relay_thread = threading.Thread(target=relay, daemon=True)
        relay_thread.start()
        try:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_process_job, remote_site, i, g, fmt, title, book_dir, work_dir,
                                       keep_tmp, shared_cancel, events) for i, g in enumerate(groups)]
                ok = []
                for i, f in enumerate(futures):
                    try:
                        ok.append(f.result())
                    except Exception as e:  # the worker process itself died
                        on_status(i, FAILED, 0.0, str(e))
                        ok.append(False)
        finally:
            stop.set()
            relay_thread.join()
        return ok
