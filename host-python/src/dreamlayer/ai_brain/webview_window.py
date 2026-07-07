"""Native panel window (macOS) — an NSWindow hosting a WKWebView that shows the
Brain control panel, so the app has a real window (like a VPN app) instead of
opening the browser.

Uses PyObjC directly (which rumps already pulls in) so the window lives on the
same AppKit run loop the menu-bar app is already driving — no second event loop
to fight, and no extra heavyweight dependency. macOS-only: every import and call
is guarded so this module loads (and no-ops) on Linux/CI, and any failure returns
False so the caller can fall back to the browser.
"""
from __future__ import annotations

# A module-level reference so the window (and its web view) survive past the
# menu callback and aren't garbage-collected out from under AppKit.
_window = None


def _load(web, url: str) -> None:
    from Foundation import NSURL, NSURLRequest
    web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))


def open_panel_window(url: str, title: str = "DreamLayer") -> bool:
    """Open — or focus, if already open — a native window showing `url`.

    Returns True on success, False if native windowing isn't available (the
    caller should then fall back to opening a browser).
    """
    global _window
    try:
        from AppKit import (NSWindow, NSApp, NSBackingStoreBuffered, NSMakeRect,
                            NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
                            NSWindowStyleMaskResizable,
                            NSWindowStyleMaskMiniaturizable,
                            NSViewWidthSizable, NSViewHeightSizable)
        from WebKit import WKWebView, WKWebViewConfiguration
        from Foundation import NSMakeSize
    except Exception:
        return False

    try:
        # already open → reload + bring to front
        if _window is not None:
            try:
                _load(_window.contentView(), url)
                _window.makeKeyAndOrderFront_(None)
                NSApp().activateIgnoringOtherApps_(True)
                return True
            except Exception:
                _window = None  # stale (window was closed) — build a fresh one

        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                 | NSWindowStyleMaskResizable | NSWindowStyleMaskMiniaturizable)
        rect = NSMakeRect(0, 0, 940, 760)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False)
        win.setTitle_(title)
        win.setMinSize_(NSMakeSize(560, 480))
        win.center()
        # keep the window around after its last strong ref goes away
        win.setReleasedWhenClosed_(False)

        conf = WKWebViewConfiguration.alloc().init()
        web = WKWebView.alloc().initWithFrame_configuration_(rect, conf)
        web.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        win.setContentView_(web)
        _load(web, url)

        win.makeKeyAndOrderFront_(None)
        NSApp().activateIgnoringOtherApps_(True)
        _window = win
        return True
    except Exception:
        return False
