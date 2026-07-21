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

# Module-level references so the window (and its web view / UI delegate)
# survive past the menu callback and aren't garbage-collected out from under
# AppKit. WKWebView holds its uiDelegate WEAKLY, so dropping ours would turn
# every confirm()/alert() in the panel back into a silent no-op.
_window = None
_ui_delegate = None


def _load(web, url: str) -> None:
    from Foundation import NSURL, NSURLRequest
    web.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(url)))


def _make_ui_delegate():
    """A WKUIDelegate that gives the panel real JS dialogs.

    A bare WKWebView has NO implementation for the JavaScript dialog hooks, so
    window.confirm() resolves false and alert() vanishes — silently. The panel
    guards destructive actions (rotate token, erase, restore backup) behind
    confirm(), so without this delegate those buttons do nothing in the native
    window while working fine in Safari. NSAlert on the main thread is the
    canonical macOS answer."""
    try:
        import objc
        from AppKit import NSAlert, NSAlertFirstButtonReturn
        from Foundation import NSObject
    except Exception:
        return None

    class _PanelUIDelegate(NSObject):  # pragma: no cover — AppKit-only path
        def webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_(
                self, webview, message, frame, handler):
            alert = NSAlert.alloc().init()
            alert.setMessageText_("DreamLayer")
            alert.setInformativeText_(str(message))
            alert.addButtonWithTitle_("OK")
            alert.runModal()
            handler()

        webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_ = objc.selector(
            webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_,
            signature=b"v@:@@@@?")

        def webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_(
                self, webview, message, frame, handler):
            alert = NSAlert.alloc().init()
            alert.setMessageText_("DreamLayer")
            alert.setInformativeText_(str(message))
            alert.addButtonWithTitle_("OK")
            alert.addButtonWithTitle_("Cancel")
            handler(alert.runModal() == NSAlertFirstButtonReturn)

        webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_ = objc.selector(
            webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_,
            signature=b"v@:@@@@?")

    try:
        return _PanelUIDelegate.alloc().init()
    except Exception:
        return None


def _set_dock_presence(on: bool) -> None:
    """The app is a menu-bar appliance (LSUIElement) — while the panel window
    is open it becomes a REGULAR app, which is what puts the white running-dot
    under the Dock icon and an entry in Cmd-Tab; closing the panel returns it
    to the quiet menu-bar-only posture. Also stamps the real app icon on the
    running process so the switcher shows DreamLayer, not a generic tile.
    Best-effort and off-Mac inert (no AppKit → no-op), like the UI delegate."""
    try:
        from AppKit import NSApp, NSImage
        # 0 = NSApplicationActivationPolicyRegular, 1 = ...Accessory
        NSApp().setActivationPolicy_(0 if on else 1)
        if on:
            from pathlib import Path
            icon = Path(__file__).resolve().parent / "server" / "assets" / "app_icon.png"
            if icon.is_file():
                img = NSImage.alloc().initWithContentsOfFile_(str(icon))
                if img is not None:
                    NSApp().setApplicationIconImage_(img)
    except Exception:
        pass


_close_delegate = None       # retained — NSWindow holds its delegate weakly


def _make_close_delegate():
    """A window delegate that drops Dock presence when the panel closes.
    Returns None off-Mac (no AppKit), mirroring _make_ui_delegate."""
    try:
        import objc
        from Foundation import NSObject

        class _PanelCloseDelegate(NSObject):
            @objc.python_method
            def _noop(self):
                pass

            def windowWillClose_(self, note):
                _set_dock_presence(False)

        return _PanelCloseDelegate.alloc().init()
    except Exception:
        return None


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
                _set_dock_presence(True)
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
        global _ui_delegate
        _ui_delegate = _make_ui_delegate()
        if _ui_delegate is not None:
            web.setUIDelegate_(_ui_delegate)
        win.setContentView_(web)
        _load(web, url)

        global _close_delegate
        _close_delegate = _make_close_delegate()
        if _close_delegate is not None:
            win.setDelegate_(_close_delegate)

        win.makeKeyAndOrderFront_(None)
        _set_dock_presence(True)
        NSApp().activateIgnoringOtherApps_(True)
        _window = win
        return True
    except Exception:
        return False
