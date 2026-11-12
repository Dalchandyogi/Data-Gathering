import csv
import hashlib
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urljoin, urlparse, unquote

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from tqdm import tqdm

# ---------------- CONFIG ----------------
URL = "https://aneetfanpage.in/gallery.html"
OUT_DIR = "aneet_images3"
HTML_DIR = "html_snapshots"           # final page HTML is saved here
STATE_FILE = "downloaded_urls.txt"  # finished URLs, one per line
SCROLL_FILE = "scroll_state.json"     # last page / <img> count reached
FOUND_FILE = "found_urls.csv"         # every URL found: page, url
MISSING_FILE = "missing_urls.txt"     # written at the end: URLs with no file on disk
BAD_FILE = "bad_files.txt"            # written at the end: files that are not real images
LOG_FILE = "scraper.log"

# MODE:
#   "resume" = skip every URL listed in downloaded_urls_0.txt (fastest rerun)
#   "verify" = ignore downloaded_urls_0.txt, check the disk for every URL and
#              download only what is missing or broken  <-- use this now
#   "fresh"  = delete all state and re-download everything (overwrites files)
MODE = "verify"

HEADLESS = False
WORKERS = 6
MAX_WAIT_PER_SCROLL = 20
MAX_IDLE_ROUNDS = 5
MIN_BYTES = 5_000
MAX_IMAGES = None
URL_FILTER = None
BLOCK_IMAGES_WHILE_FAST_FORWARD = False   # True = faster re-scroll, but test it first
# ----------------------------------------

IMG_EXT = re.compile(r"\.(jpe?g|png|webp|gif)$", re.I)
file_lock = threading.Lock()


class TqdmHandler(logging.Handler):
    def emit(self, record):
        tqdm.write(self.format(record))


def setup_logging():
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")
    lg = logging.getLogger("scraper")
    lg.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = TqdmHandler()
    ch.setFormatter(fmt)
    lg.addHandler(fh)
    lg.addHandler(ch)
    return lg


log = setup_logging()


# ---------- state files ----------
def load_done():
    if not os.path.exists(STATE_FILE):
        return set()
    with open(STATE_FILE, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_done(url):
    with file_lock, open(STATE_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def load_scroll_state():
    try:
        with open(SCROLL_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return int(d.get("page", 0)), int(d.get("imgs", 0))
    except Exception:
        return 0, 0


def save_scroll_state(page, imgs):
    with open(SCROLL_FILE, "w", encoding="utf-8") as f:
        json.dump({"page": page, "imgs": imgs,
                   "time": datetime.now().isoformat(timespec="seconds")}, f)


def record_found(page, url):
    with file_lock:
        new_file = not os.path.exists(FOUND_FILE)
        with open(FOUND_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["page", "url"])
            w.writerow([page, url])


# ---------- browser ----------
def make_driver():
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-gpu")
    return webdriver.Chrome(options=opts)


def block_images(driver, on=True):
    driver.execute_cdp_cmd("Network.enable", {})
    driver.execute_cdp_cmd(
        "Network.setBlockedURLs",
        {"urls": ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif"] if on else []},
    )


GRAB_JS = """
const imgs = [], links = [];
let empty = 0;
document.querySelectorAll('img').forEach(i => {
  let s = i.dataset.src || i.dataset.original || i.dataset.lazySrc || i.dataset.full
          || i.currentSrc || i.src;
  if (!s) {
    const ss = i.dataset.srcset || i.getAttribute('srcset');
    if (ss) s = ss.split(',').pop().trim().split(' ')[0];
  }
  if (s && !s.startsWith('data:')) imgs.push(s); else empty++;
});
document.querySelectorAll('a[href]').forEach(a => links.push(a.href));
return [imgs, links, document.images.length, document.body.scrollHeight, empty];
"""

COUNT_JS = "return [document.images.length, document.body.scrollHeight];"


def is_http(u):
    return urlparse(u).scheme in ("http", "https")


def grab(driver):
    imgs, links, n_imgs, height, empty = driver.execute_script(GRAB_JS)
    base = driver.current_url
    urls = set()
    for u in imgs:                       # <img> sources: any http(s) URL
        full = urljoin(base, u)
        if is_http(full):
            urls.add(full)
    for u in links:                      # <a> links: only direct image files
        full = urljoin(base, u)
        if is_http(full) and IMG_EXT.search(urlparse(full).path):
            urls.add(full)
    return sorted(urls), n_imgs, height, empty


# ---------- download ----------
def looks_like_image(head):
    return (head[:3] == b"\xff\xd8\xff"
            or head[:8] == b"\x89PNG\r\n\x1a\n"
            or head[:4] == b"GIF8"
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"))


def is_image_file(path):
    try:
        with open(path, "rb") as f:
            return looks_like_image(f.read(12))
    except OSError:
        return False


def filename_for(url):
    path = unquote(urlparse(url).path)
    stem, ext = os.path.splitext(os.path.basename(path))
    ext = ext if ext.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg"
    h = hashlib.md5(url.encode()).hexdigest()[:6]
    return f"{stem or 'image'}_{h}{ext}"


def download(url, session, overwrite):
    path = os.path.join(OUT_DIR, filename_for(url))
    if os.path.exists(path) and not overwrite:
        if is_image_file(path):
            return "skip", url
        os.remove(path)                  # broken or non-image file from an old run
        log.warning(f"removed bad file {os.path.basename(path)}, re-downloading")
    for attempt in range(1, 4):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            data = r.content
            if len(data) < MIN_BYTES:
                return "small", url
            if not looks_like_image(data[:12]):
                return "notimg", url     # e.g. an HTML page, not a picture
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            return "ok", url
        except Exception as e:
            log.warning(f"retry {attempt}/3 for {url}: {e}")
            time.sleep(1.5 * attempt)
    return "fail", url


# ---------- end-of-run checks ----------
def save_html(driver):
    try:
        os.makedirs(HTML_DIR, exist_ok=True)
        name = f"gallery_{datetime.now():%Y%m%d_%H%M%S}.html"
        path = os.path.join(HTML_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log.info(f"HTML snapshot saved: {path}")
    except Exception as e:
        log.warning(f"Could not save HTML snapshot: {e}")


def final_report(queued, no_file, page_imgs, last_page):
    files = os.listdir(OUT_DIR)
    parts = [f for f in files if f.endswith(".part")]
    good, bad = 0, []
    for f in files:
        if f.endswith(".part"):
            continue
        if is_image_file(os.path.join(OUT_DIR, f)):
            good += 1
        else:
            bad.append(f)

    missing = [u for u in sorted(queued)
               if u not in no_file
               and not os.path.exists(os.path.join(OUT_DIR, filename_for(u)))]

    with open(MISSING_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(missing))
    with open(BAD_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(bad))

    log.info("=" * 60)
    log.info(f"REPORT | last page reached: {last_page}")
    log.info(f"REPORT | <img> elements on page: {page_imgs}")
    log.info(f"REPORT | unique URLs found: {len(queued)}")
    log.info(f"REPORT | valid images on disk: {good}")
    log.info(f"REPORT | not real images (see {BAD_FILE}): {len(bad)}")
    log.info(f"REPORT | leftover .part files: {len(parts)}")
    log.info(f"REPORT | URLs with no file (see {MISSING_FILE}): {len(missing)}")
    if missing or parts:
        log.info("Rerun with MODE = 'verify' to retry the missing ones.")
    log.info("=" * 60)


# ---------- main ----------
def run():
    os.makedirs(OUT_DIR, exist_ok=True)
    overwrite = MODE == "fresh"
    if MODE == "fresh":
        for f in (STATE_FILE, SCROLL_FILE):
            if os.path.exists(f):
                os.remove(f)
    if MODE != "resume" and os.path.exists(FOUND_FILE):
        os.remove(FOUND_FILE)

    done = load_done() if MODE == "resume" else set()
    queued = set(done)
    no_file = set()                      # URLs that are final but have no file (tiny / not image)
    stats = {"ok": 0, "skip": 0, "small": 0, "notimg": 0, "fail": 0}
    resume_page, resume_imgs = load_scroll_state()
    best = [resume_page, resume_imgs]    # furthest position ever reached

    log.info(f"MODE = {MODE} | {len(done)} URLs already marked done")
    if resume_page:
        log.info(f"Last run stopped at page {resume_page} (~{resume_imgs} <img>). "
                 f"Will scroll from page 1 up to there, then new images begin.")
    else:
        log.info("No saved position, starting from page 1")

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": URL})

    pbar = tqdm(total=len(done), initial=len(done), unit="img", desc="Page 1")
    pool = ThreadPoolExecutor(max_workers=WORKERS)

    def on_done(fut):
        try:
            status, url = fut.result()
        except Exception as e:
            log.error(f"worker crashed: {e}")
            return
        stats[status] += 1
        if status in ("ok", "skip", "small", "notimg"):
            mark_done(url)
        if status in ("small", "notimg"):
            no_file.add(url)
            log.info(f"ignored ({status}): {url}")
        if status == "fail":
            log.error(f"FAILED {url}")
        pbar.update(1)
        pbar.set_postfix(ok=stats["ok"], skip=stats["skip"], fail=stats["fail"])

    def queue_new(urls, page):
        new = [u for u in urls if u not in queued
               and (URL_FILTER is None or re.search(URL_FILTER, u))]
        count = 0
        for u in new:
            if MAX_IMAGES and len(queued) >= MAX_IMAGES:
                break
            queued.add(u)
            record_found(page, u)
            pbar.total += 1
            pool.submit(download, u, session, overwrite).add_done_callback(on_done)
            count += 1
        return count

    driver = make_driver()
    page = 1
    page_imgs = 0
    completed = False
    try:
        log.info(f"Opening {URL}")
        driver.get(URL)
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "img"))
        )

        blocking = BLOCK_IMAGES_WHILE_FAST_FORWARD and resume_imgs > 0
        if blocking:
            block_images(driver, True)
            log.info("Fast-forward: image loading blocked until old position is reached")

        was_fast = resume_imgs > 0
        idle = 0
        while idle < MAX_IDLE_ROUNDS:
            urls, n_imgs, height, empty = grab(driver)
            page_imgs = n_imgs
            fast = n_imgs < resume_imgs

            if was_fast and not fast:
                log.info(f"*** Reached previous stop (page {resume_page}). "
                         f"New images start from page {page} ***")
                if blocking:
                    block_images(driver, False)
                    blocking = False
            was_fast = fast

            added = queue_new(urls, page)
            phase = "FAST-FORWARD" if fast else "NEW"
            target = f"/{resume_page}" if resume_page else ""
            pbar.set_description(f"Page {page}{target} [{phase}]")
            log.info(f"[{phase}] page {page}{target} | <img> on page: {n_imgs} "
                     f"| new URLs queued: {added} | imgs without URL: {empty} "
                     f"| total URLs: {len(queued)}")

            if page > best[0] or n_imgs > best[1]:
                best = [max(page, best[0]), max(n_imgs, best[1])]
                save_scroll_state(*best)

            if MAX_IMAGES and len(queued) >= MAX_IMAGES:
                log.info("MAX_IMAGES reached")
                break

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            poll = 0.1 if fast else 0.3
            changed = False
            t0 = time.time()
            while time.time() - t0 < MAX_WAIT_PER_SCROLL:
                time.sleep(poll)
                n2, h2 = driver.execute_script(COUNT_JS)
                if n2 > n_imgs or h2 > height:
                    changed = True
                    break

            if changed:
                idle = 0
                page += 1
            else:
                idle += 1
                log.info(f"No new content on page {page} ({idle}/{MAX_IDLE_ROUNDS})")
                driver.execute_script("window.scrollBy(0, -500);")
                time.sleep(0.5)

        log.info(f"Reached end of gallery at page {page}. Waiting for downloads to finish")
        urls, n_imgs, _, _ = grab(driver)
        page_imgs = n_imgs
        queue_new(urls, page)
        save_scroll_state(max(page, best[0]), max(n_imgs, best[1]))
        completed = True

    except KeyboardInterrupt:
        log.warning(f"Interrupted at page {page}. Progress is saved, rerun to resume.")
        pool.shutdown(wait=False, cancel_futures=True)
    finally:
        save_html(driver)
        driver.quit()
        pool.shutdown(wait=True)
        pbar.close()
        log.info(f"Finished: {stats}")

    if completed:
        final_report(queued, no_file, page_imgs, page)


if __name__ == "__main__":
    run()