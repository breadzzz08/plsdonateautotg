"""
╭─────────────────────────────────────────────────────────────╮
│                                                             │
│  ███╗   ███╗ █████╗ ███╗   ██╗██████╗ ██████╗ ███████╗      │
│  ████╗ ████║██╔══██╗████╗  ██║██╔══██╗██╔══██╗██╔════╝      │
│  ██╔████╔██║███████║██╔██╗ ██║██║  ██║██████╔╝█████╗        │
│  ██║╚██╔╝██║██╔══██║██║╚██╗██║██║  ██║██╔══██╗██╔══╝        │
│  ██║ ╚═╝ ██║██║  ██║██║ ╚████║██████╔╝██║  ██║███████╗      │
│  ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝ ╚═╝  ╚═╝╚══════╝      │
│                                                             │
│         █████╗ ██╗                                          │
│        ██╔══██╗██║    ╭───────────────────╮                 │
│        ███████║██║    │© 2024-2025        │                 │
│        ██╔══██║██║    │Licensed Product   │                 │
│        ██║  ██║██║    │All Rights Reserved│                 │
│        ╚═╝  ╚═╝╚═╝    ╰───────────────────╯                 │
│                                                             │
│  ╭───────────────────────────────────────────────────────╮  │
│  │ Unauthorized use, reproduction or distribution        │  │
│  │ of this software is strictly prohibited               │  │
│  ╰───────────────────────────────────────────────────────╯  │
│                                                             │
╰─────────────────────────────────────────────────────────────╯
"""
#  /\_/\
# ( o.o )
#  > ^ <
# Кот, который починил утечку памяти. Мяу.

import traceback
from base_plugin import BasePlugin, MethodReplacement
from ui.settings import Header, Input, Divider, Text
from hook_utils import find_class
from android_utils import log, run_on_ui_thread
from java import dynamic_proxy, jclass
from java.lang import Runnable
from android.view import View
from android.widget import FrameLayout
from android.os import Handler, Looper
import threading
import requests
from android.net import Uri
from android.graphics import Color
import hashlib
from urllib.parse import urlparse

# ВАЖНО ТУТ НАСТРЙКИ МОГУТ НАХУЙ НАЕБНУТЬ ВЕСЬ КЛИЕНТ, редактируем АКУРАТНО! 
VIDEO_URL = "https://github.com/sterepandopalcevsto/supreme-octo-palm-tree/raw/refs/heads/main/uOPpbAEGb8mZFYRQ.mp4"  # RAW MP4 URL
VIDEO_MUTE = True
VIDEO_LOOP = True
VIDEO_ENABLED = True
LOCAL_FILE_NAME = "uOPpbAEGb8mZFYRQ.mp4"
PREFETCH_ON_LOAD = True
TARGET_FPS = 9
PREFERRED_BITRATE = 60000  # ~0.06 Mbps
USE_TEXTURE_VIEW = False  # Prefer SurfaceView for stability on some devices
HOOK_PLAYER_ERROR = True  # Hook error lambda to avoid delegate NPE
HOOK_INTERNAL_CALLBACKS = False  # Do NOT hook per-frame/player callbacks (prevents FPS overhead)
HOOK_STATE_GUARD = False  # Disabled by default to avoid interfering with chat video playback


def _acw_sanitize_filename_from_url(url: str):
    try:
        path = urlparse(url or "").path or ""
        name = path.split("/")[-1] or ""
        if not name:
            name = hashlib.md5((url or "").encode("utf-8")).hexdigest() + ".mp4"
        # allow alnum, dash, underscore, dot
        name = "".join(c for c in name if c.isalnum() or c in ("-", "_", "."))
        if len(name) < 3:
            name = hashlib.md5((url or "").encode("utf-8")).hexdigest() + ".mp4"
        return name
    except Exception:
        return "acw_" + str(abs(hash(url or ""))) + ".mp4"


def _acw_get_local_file_for_url(ctx, url: str):
    try:
        FileCls = jclass("java.io.File")
        cache_dir = ctx.getCacheDir()
        fname = _acw_sanitize_filename_from_url(url)
        return FileCls(cache_dir, fname)
    except Exception:
        return None

__id__ = "animated_chat_wallpaper"
__name__ = "AnimatedChatWallpaper"
__description__ = "Set MP4 URL as animated chat wallpaper"
__author__ = """MandreAI & СвагаНеТута
@swagnonher & @MandreAI_bot"""
__min_version__ = "11.12.0"
__icon__ = "exteraPlugins/0"
__version__ = "1.1"


class AnimatedChatWallpaperPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self._chat_resume_ref = None
        self._chat_pause_ref = None
        self._chat_destroy_ref = None
        self._chat_create_view_ref = None
        # Internal VideoPlayer hooks refs (to guard against null delegate callbacks)
        self._vp_tex_hook_ref = None
        self._vp_state_hook_ref = None
        self._vp_size_hook_ref = None
        self._vp_first_frame_hook_ref = None
        self._vp_error_hook_ref = None
        self._vp_error_lambda_hook_ref = None
        # Settings keys and cached values
        self.SETTINGS_URL_KEY = "acw_video_url"
        self.SETTINGS_FPS_KEY = "acw_target_fps"
        self.SETTINGS_BITRATE_KEY = "acw_preferred_bitrate"
        self._cached_url = VIDEO_URL
        self._cached_fps = TARGET_FPS
        self._cached_bitrate = PREFERRED_BITRATE
        self._vp_state_hook_ref = None
        # Global reusable holder to avoid codec churn across chats
        self._global_holder = None

    def on_plugin_load(self):
        # Load settings persisted values and sync runtime variables
        try:
            self._load_settings()
        except Exception:
            pass
        try:
            ChatActivity = find_class("org.telegram.ui.ChatActivity")
            if not ChatActivity:
                log("[ACW] ChatActivity not found")
                return
            # Hook ChatActivity.onResume/onPause/onFragmentDestroy to manage player
            on_resume = ChatActivity.getClass().getDeclaredMethod("onResume")
            on_resume.setAccessible(True)
            self._chat_resume_ref = self.hook_method(on_resume, _ChatResumeHook(self))

            on_pause = ChatActivity.getClass().getDeclaredMethod("onPause")
            on_pause.setAccessible(True)
            self._chat_pause_ref = self.hook_method(on_pause, _ChatPauseHook(self))

            on_destroy = ChatActivity.getClass().getDeclaredMethod("onFragmentDestroy")
            on_destroy.setAccessible(True)
            self._chat_destroy_ref = self.hook_method(on_destroy, _ChatDestroyHook(self))
            # Also hook view creation to attach earlier
            try:
                ContextClass = find_class("android.content.Context")
                create_view = ChatActivity.getClass().getDeclaredMethod("createView", ContextClass)
                create_view.setAccessible(True)
                self._chat_create_view_ref = self.hook_method(create_view, _ChatCreateViewHook(self))
            except Exception:
                pass
            log("[ACW] Hooks installed for ChatActivity lifecycle + createView")
        except Exception:
            log(f"[ACW] Failed to hook ChatActivity lifecycle: {traceback.format_exc()}")

        # Guard player state reporting to avoid null delegate NPE seen on first re-entry
        if True and HOOK_STATE_GUARD:
            try:
                VPObj = find_class("org.telegram.ui.Components.VideoPlayer")
                VPClass = VPObj.getClass() if hasattr(VPObj, "getClass") else VPObj
                m = VPClass.getDeclaredMethod("maybeReportPlayerState")
                m.setAccessible(True)
                self._vp_state_hook_ref = self.hook_method(m, _VideoPlayerStateHook())
                # Also guard size/first-frame callbacks which may dereference delegate
                try:
                    m2 = VPClass.getDeclaredMethod("onVideoSizeChanged", jclass("com.google.android.exoplayer2.video.VideoSize"))
                    m2.setAccessible(True)
                    self._vp_size_hook_ref = self.hook_method(m2, _VideoPlayerSizeHook())
                except Exception:
                    pass
                try:
                    m3 = VPClass.getDeclaredMethod("onRenderedFirstFrame")
                    m3.setAccessible(True)
                    self._vp_first_frame_hook_ref = self.hook_method(m3, _VideoPlayerFirstFrameHook())
                except Exception:
                    pass
                log("[ACW] Hooked player guards (state/size/first-frame)")
            except Exception:
                pass

        # Hook internal player callbacks only when explicitly enabled (avoid interfering with Telegram players)
        if HOOK_INTERNAL_CALLBACKS:
            try:
                VPObj = find_class("org.telegram.ui.Components.VideoPlayer")
                VPClass = VPObj.getClass() if hasattr(VPObj, "getClass") else VPObj
                for name, hook in [
                    ("onSurfaceTextureUpdated", _VideoPlayerTexUpdateHook()),
                    ("maybeReportPlayerState", _VideoPlayerStateHook()),
                    ("onRenderedFirstFrame", _VideoPlayerFirstFrameHook()),
                ]:
                    try:
                        if name == "onSurfaceTextureUpdated":
                            m = VPClass.getDeclaredMethod(name, jclass("android.graphics.SurfaceTexture"))
                        else:
                            m = VPClass.getDeclaredMethod(name)
                        m.setAccessible(True)
                        self.hook_method(m, hook)
                    except Exception:
                        pass
                try:
                    m = VPClass.getDeclaredMethod("onVideoSizeChanged", jclass("com.google.android.exoplayer2.video.VideoSize"))
                    m.setAccessible(True)
                    self.hook_method(m, _VideoPlayerSizeHook())
                except Exception:
                    pass
                try:
                    m = VPClass.getDeclaredMethod("onSurfaceDestroyed", jclass("android.graphics.SurfaceTexture"))
                    m.setAccessible(True)
                    self.hook_method(m, _VideoPlayerSurfaceDestroyedHook())
                except Exception:
                    pass
                try:
                    m = VPClass.getDeclaredMethod("onPlayerError", jclass("com.google.android.exoplayer2.PlaybackException"))
                    m.setAccessible(True)
                    self.hook_method(m, _VideoPlayerOnErrorLogHook())
                except Exception:
                    pass
                if HOOK_PLAYER_ERROR:
                    try:
                        m = VPClass.getDeclaredMethod("lambda$onPlayerError$1", jclass("com.google.android.exoplayer2.PlaybackException"))
                        m.setAccessible(True)
                        self.hook_method(m, _VideoPlayerErrorLambdaHook())
                    except Exception:
                        try:
                            m = VPClass.getDeclaredMethod("lambda$onPlayerError$1")
                            m.setAccessible(True)
                            self.hook_method(m, _VideoPlayerErrorLambdaHook())
                        except Exception:
                            pass
                log("[ACW] Hooked internal VideoPlayer callbacks (opt-in)")
            except Exception:
                pass

        # Prefetch video into local storage right after plugin install/load
        if PREFETCH_ON_LOAD:
            try:
                ApplicationLoader = jclass("org.telegram.messenger.ApplicationLoader")
                FileCls = jclass("java.io.File")
                ctx = ApplicationLoader.applicationContext
                cache_dir = ctx.getCacheDir()
                local_file = FileCls(cache_dir, LOCAL_FILE_NAME)
                def _prefetch():
                    try:
                        # Skip if already downloaded
                        if local_file.exists() and local_file.length() > 0:
                            log("[ACW] Prefetch: local file already present")
                            return
                        dest_path = local_file.getAbsolutePath()
                        log(f"[ACW] Prefetch: downloading to {dest_path}")
                        r = requests.get(VIDEO_URL, stream=True, timeout=60)
                        r.raise_for_status()
                        with open(dest_path, "wb") as f:
                            for chunk in r.iter_content(1024 * 256):
                                if chunk:
                                    f.write(chunk)
                        log("[ACW] Prefetch: download complete")
                    except Exception:
                        log(f"[ACW] Prefetch failed: {traceback.format_exc()}")
                threading.Thread(target=_prefetch, daemon=True).start()
            except Exception:
                log(f"[ACW] Prefetch setup failed: {traceback.format_exc()}")

    def create_settings(self):
        try:
            url = self.get_setting(self.SETTINGS_URL_KEY, VIDEO_URL)
            fps = str(self.get_setting(self.SETTINGS_FPS_KEY, TARGET_FPS))
            bitrate = str(self.get_setting(self.SETTINGS_BITRATE_KEY, PREFERRED_BITRATE))
        except Exception:
            url = VIDEO_URL
            fps = str(TARGET_FPS)
            bitrate = str(PREFERRED_BITRATE)
        return [
            Header("Animated Chat Wallpaper"),
            Input(
                "video_url",
                "RAW видео URL",
                default=url,
                icon="msg_video",
                subtext="Укажите прямую RAW-ссылку на MP4/WEBM. Пример: https://github.com/<user>/<repo>/raw/<branch>/file.mp4",
                on_change=self._on_url_change,
            ),
            Divider(),
            Input(
                "target_fps",
                "Ориентирный FPS",
                default=fps,
                icon="msg_speed",
                subtext="Чем ниже FPS, тем меньше нагрузка и расход батареи. Реальная частота зависит от устройства.",
                on_change=self._on_fps_change,
            ),
            Divider(),
            Input(
                "preferred_bitrate",
                "Ориентирный битрейт (bps)",
                default=bitrate,
                icon="msg_info",
                subtext="Верхний лимит пиковой скорости потока/декодирования. Фактический битрейт зависит от источника и устройства.",
                on_change=self._on_bitrate_change,
            ),
        ]

    def _load_settings(self):
        global VIDEO_URL, TARGET_FPS, PREFERRED_BITRATE
        try:
            if self.get_setting(self.SETTINGS_URL_KEY, None) is None:
                self.set_setting(self.SETTINGS_URL_KEY, VIDEO_URL)
            if self.get_setting(self.SETTINGS_FPS_KEY, None) is None:
                self.set_setting(self.SETTINGS_FPS_KEY, TARGET_FPS)
            if self.get_setting(self.SETTINGS_BITRATE_KEY, None) is None:
                self.set_setting(self.SETTINGS_BITRATE_KEY, PREFERRED_BITRATE)
        except Exception:
            pass
        try:
            self._cached_url = self.get_setting(self.SETTINGS_URL_KEY, VIDEO_URL)
            self._cached_fps = int(self.get_setting(self.SETTINGS_FPS_KEY, TARGET_FPS))
            self._cached_bitrate = int(self.get_setting(self.SETTINGS_BITRATE_KEY, PREFERRED_BITRATE))
            VIDEO_URL = self._cached_url
            TARGET_FPS = self._cached_fps
            PREFERRED_BITRATE = self._cached_bitrate
            log(f"[ACW] Settings loaded: url={VIDEO_URL}, fps={TARGET_FPS}, bitrate={PREFERRED_BITRATE}")
        except Exception:
            pass

    def _get_active_holder(self):
        try:
            return getattr(self, "_global_holder", None)
        except Exception:
            return None

    def _on_url_change(self, value: str):
        global VIDEO_URL
        try:
            url = (value or "").strip()
            self.set_setting(self.SETTINGS_URL_KEY, url)
            VIDEO_URL = url
            self._cached_url = url
            log(f"[ACW] URL updated via settings: {url}")
        except Exception:
            pass
        try:
            holder = self._get_active_holder()
            if holder is not None and holder.player is not None:
                def run():
                    try:
                        if holder.ensure_attached():
                            # Pause wallpaper while user interacts with a chat video
                            try:
                                holder.pause()
                                if holder.container is not None:
                                    holder.container.setAlpha(0.0)
                            except Exception:
                                pass
                            if holder.ensure_player(self._cached_url, bool(VIDEO_MUTE), bool(VIDEO_LOOP)):
                                try:
                                    holder.player.setPlayWhenReady(True)
                                    holder.player.seekTo(0)
                                    holder.player.play()
                                    log("[ACW] Applied new URL and restarted playback")
                                except Exception:
                                    pass
                    except Exception:
                        pass
                run_on_ui_thread(run)
        except Exception:
            pass

    def _on_fps_change(self, value: str):
        global TARGET_FPS
        try:
            fps = int(str(value).strip())
            if fps <= 0 or fps > 120:
                raise ValueError()
            self.set_setting(self.SETTINGS_FPS_KEY, fps)
            TARGET_FPS = fps
            self._cached_fps = fps
            log(f"[ACW] Target FPS updated via settings: {fps}")
        except Exception:
            try:
                self.set_setting("target_fps", str(self._cached_fps))
            except Exception:
                pass
        try:
            holder = self._get_active_holder()
            if holder is not None:
                def run():
                    try:
                        if holder.player is not None:
                            try:
                                holder.player.setPreferredFrameRate(float(self._cached_fps))
                            except Exception:
                                pass
                        try:
                            if holder.surface_view is not None:
                                surf_holder = holder.surface_view.getHolder()
                                surf = surf_holder.getSurface()
                                if surf is not None:
                                    try:
                                        surf.setFrameRate(float(self._cached_fps), 0)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    except Exception:
                        pass
                run_on_ui_thread(run)
        except Exception:
            pass

    def _on_bitrate_change(self, value: str):
        global PREFERRED_BITRATE
        try:
            br = int(str(value).strip())
            if br < 10000:
                br = 10000
            self.set_setting(self.SETTINGS_BITRATE_KEY, br)
            PREFERRED_BITRATE = br
            self._cached_bitrate = br
            log(f"[ACW] Preferred bitrate updated via settings: {br}")
        except Exception:
            try:
                self.set_setting("preferred_bitrate", str(self._cached_bitrate))
            except Exception:
                pass
        try:
            holder = self._get_active_holder()
            if holder is not None and holder.player is not None:
                def run():
                    try:
                        try:
                            holder.player.setPreferredPeakBitrate(int(self._cached_bitrate))
                            log("[ACW] Applied new preferred peak bitrate")
                        except Exception:
                            pass
                    except Exception:
                        pass
                run_on_ui_thread(r