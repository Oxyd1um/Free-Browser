import gi
import os
import json
import sqlite3
import threading
from urllib.parse import quote_plus, urlsplit

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
gi.require_version("Soup", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("Soup", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gtk, WebKit, GLib, Gdk, Gio, Soup, Pango
import connections


class Browser:
    SEARCH_ENGINES = {
        "isci.si (SearXNG)": "https://www.isci.si/search?q={query}",
        "DuckDuckGo (No-AI)": "https://noai.duckduckgo.com/?q={query}",
        "DuckDuckGo Lite": "https://lite.duckduckgo.com/lite/?q={query}",
        "Wikipedia": "https://en.wikipedia.org/w/index.php?search={query}",
        "Add your search engine": "custom"
    }
    SECURITY_MODES = ["Normal", "Strict", "Low"]
    THEMES = ["System", "Light", "Dark"]
    GPL_URL = "https://www.gnu.org/licenses/gpl-3.0.html"

    def __init__(self, app):
        self.app = app
        self.tabs = []
        self.active = None
        self.tab_id = 0
        self.cookie_window = None
        self.cookie_list = None
        self.settings_open = False

        self.data_dir = os.path.join(GLib.get_user_data_dir(), "free-browser")
        self.config_dir = os.path.join(GLib.get_user_config_dir(), "free-browser")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)

        self.config_path = os.path.join(self.config_dir, "settings.json")
        self.history_path = os.path.join(self.data_dir, "history.sqlite3")
        self.cookie_path = os.path.join(self.data_dir, "cookies.sqlite")
        self.config = self.load_config()
        self.history = sqlite3.connect(self.history_path)
        self.history.execute(
            "CREATE TABLE IF NOT EXISTS visits ("
            "id INTEGER PRIMARY KEY, title TEXT, url TEXT, visited_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.history.commit()

        self.session = WebKit.NetworkSession.get_default()
        self.cookie_manager = self.session.get_cookie_manager()
        self.cookie_manager.set_persistent_storage(
            self.cookie_path, WebKit.CookiePersistentStorage.SQLITE
        )
        WebKit.WebContext.get_default().set_cache_model(
            WebKit.CacheModel.DOCUMENT_BROWSER
        )

        self.gtk_settings = Gtk.Settings.get_default()
        self.system_dark = self.gtk_settings.get_property(
            "gtk-application-prefer-dark-theme"
        )

        self.install_css()
        self.build_ui()
        self.apply_theme()
        self.new_tab()

    def load_config(self):
        defaults = {
            "search_engine": "isci.si (SearXNG)",
            "custom_search_url": "",
            "security": "Normal",
            "theme": "System"
        }
        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            defaults.update(data)
        except (OSError, ValueError, TypeError):
            pass
        if defaults["search_engine"] not in self.SEARCH_ENGINES:
            defaults["search_engine"] = "isci.si (SearXNG)"
        if defaults["security"] not in self.SECURITY_MODES:
            defaults["security"] = "Normal"
        if defaults["theme"] not in self.THEMES:
            defaults["theme"] = "System"
        return defaults

    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as file:
            json.dump(self.config, file, indent=2)

    def install_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(b"""
            button.active {
                background-color: #3584e4;
                color: white;
            }
            .page-heading { font-size: 1.45em; font-weight: bold; }
            .muted { opacity: 0.72; }
            .history-row { padding: 5px; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def apply_theme(self):
        theme = self.config["theme"]
        if theme == "Dark":
            dark = True
        elif theme == "Light":
            dark = False
        else:
            dark = self.system_dark
        self.gtk_settings.set_property("gtk-application-prefer-dark-theme", dark)

    def box(self, vertical=True, spacing=8):
        return Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
            spacing=spacing
        )

    def heading(self, text):
        label = Gtk.Label(label=text)
        label.add_css_class("page-heading")
        label.set_xalign(0)
        return label

    def clear_box(self, widget):
        child = widget.get_first_child()
        while child:
            widget.remove(child)
            child = widget.get_first_child()

    def build_ui(self):
        self.window = Gtk.ApplicationWindow(application=self.app)
        self.window.set_title("Free Browser")
        self.window.set_default_size(1200, 840)

        self.url = Gtk.Entry()
        self.url.set_placeholder_text("Enter URL or search...")
        self.url.set_hexpand(True)
        self.url.connect("activate", self.load_address)

        self.back = Gtk.Button(label="←")
        self.forward = Gtk.Button(label="→")
        self.home = Gtk.Button(label="⌂ Main Page")
        self.load_stack = Gtk.Stack()
        self.load_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.load_stack.add_named(Gtk.Label(label="↻"), "reload")
        self.spinner = Gtk.Spinner()
        self.load_stack.add_named(self.spinner, "loading")
        self.load_button = Gtk.Button()
        self.load_button.set_child(self.load_stack)
        self.back.connect("clicked", lambda *_: self.active["web"].go_back() if self.active else None)
        self.forward.connect("clicked", lambda *_: self.active["web"].go_forward() if self.active else None)
        self.home.connect("clicked", lambda *_: self.show_home())
        self.load_button.connect("clicked", self.toggle_load)

        top_bar = self.box(False, 6)
        top_bar.set_margin_top(8)
        top_bar.set_margin_bottom(8)
        top_bar.set_margin_start(8)
        top_bar.set_margin_end(8)
        for widget in (self.back, self.forward, self.load_button, self.home, self.url):
            top_bar.append(widget)

        self.tab_list = Gtk.ListBox()
        self.tab_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.tab_list.connect("row-selected", self.switch_tab)
        tab_scroll = Gtk.ScrolledWindow()
        tab_scroll.set_child(self.tab_list)
        tab_scroll.set_vexpand(True)

        self.add_tab_button = Gtk.Button(label="+ New Tab")
        self.add_tab_button.connect("clicked", lambda *_: self.new_tab())
        self.history_button = Gtk.Button(label="History")
        self.history_button.connect("clicked", lambda *_: self.show_history())
        self.settings_button = Gtk.Button(label="Settings")
        self.settings_button.connect("clicked", self.toggle_settings)

        sidebar = self.box(True, 6)
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(190, -1)
        sidebar.set_margin_top(2)
        sidebar.set_margin_bottom(8)
        sidebar.set_margin_start(8)
        sidebar.set_margin_end(6)
        sidebar.append(self.add_tab_button)
        sidebar.append(tab_scroll)
        sidebar.append(self.history_button)
        sidebar.append(self.settings_button)

        self.tab_stack = Gtk.Stack()
        self.tab_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.tab_stack.set_hexpand(True)
        self.tab_stack.set_vexpand(True)

        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.content_stack.set_hexpand(True)
        self.content_stack.set_vexpand(True)
        self.content_stack.add_named(self.tab_stack, "browser")
        self.content_stack.add_named(self.build_settings_page(), "settings")
        self.content_stack.add_named(self.build_history_page(), "history")
        self.content_stack.add_named(self.build_about_page(), "about")

        content = self.box(False, 0)
        content.append(sidebar)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        content.append(self.content_stack)

        self.progress = Gtk.ProgressBar()
        self.progress.set_size_request(110, 5)
        self.load_label = Gtk.Label(label="Ready")
        self.net_label = Gtk.Label(label="Network: waiting")
        self.status_bar = self.box(False, 8)
        self.status_bar.set_halign(Gtk.Align.CENTER)
        self.status_bar.set_margin_bottom(5)
        self.status_bar.append(self.progress)
        self.status_bar.append(self.load_label)
        self.status_bar.append(self.net_label)
        self.status_bar.set_visible(False)

        root = self.box(True, 0)
        root.append(top_bar)
        root.append(content)
        root.append(self.status_bar)
        self.window.set_child(root)
        self.window.present()

    def build_home_page(self, tab):
        page = self.box(True, 14)
        page.set_halign(Gtk.Align.CENTER)
        page.set_valign(Gtk.Align.CENTER)
        page.set_margin_start(28)
        page.set_margin_end(28)
        page.set_size_request(420, -1)

        title = Gtk.Label(label="Search, Just like you used to.")
        title.add_css_class("page-heading")
        title.set_wrap(True)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Search the web...")
        entry.set_hexpand(True)
        search_button = Gtk.Button(label="Search")
        search_button.set_halign(Gtk.Align.CENTER)
        entry.connect("activate", lambda *_: self.search(entry.get_text(), tab))
        search_button.connect("clicked", lambda *_: self.search(entry.get_text(), tab))

        page.append(title)
        page.append(entry)
        page.append(search_button)
        tab["search_entry"] = entry
        return page

    def new_tab(self):
        self.tab_id += 1
        web = WebKit.WebView(network_session=self.session)
        settings = web.get_settings()
        settings.set_enable_smooth_scrolling(False)
        settings.set_user_agent_with_application_details("FreeBrowser", "0.1")

        tab_stack = Gtk.Stack()
        tab_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        tab_stack.set_hexpand(True)
        tab_stack.set_vexpand(True)
        tab = {
            "web": web,
            "stack": tab_stack,
            "row": None,
            "label": None,
            "probe_id": 0,
            "network": "Network: waiting",
            "resource": "",
            "pending": False,
            "name": str(self.tab_id)
        }

        home_page = self.build_home_page(tab)
        tab_stack.add_named(home_page, "home")
        tab_stack.add_named(web, "web")

        title = Gtk.Label(label="New Tab")
        title.set_xalign(0)
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_hexpand(True)
        close = Gtk.Button(label="×")
        close.set_tooltip_text("Close tab")
        row_box = self.box(False, 4)
        row_box.append(title)
        row_box.append(close)
        row = Gtk.ListBoxRow()
        row.set_child(row_box)
        tab["row"] = row
        tab["label"] = title

        self.tabs.append(tab)
        self.tab_list.append(row)
        self.tab_stack.add_named(tab_stack, tab["name"])
        close.connect("clicked", lambda *_: self.close_tab(tab))

        web.connect("notify::title", lambda *_: self.update_title(tab))
        web.connect("notify::uri", lambda *_: self.update_uri(tab))
        web.connect("notify::is-loading", lambda *_: self.update_loading(tab))
        web.connect("notify::estimated-load-progress", lambda *_: self.update_progress(tab))
        web.connect("notify::can-go-back", lambda *_: self.update_navigation())
        web.connect("notify::can-go-forward", lambda *_: self.update_navigation())
        web.connect("resource-load-started", lambda view, resource, request: self.resource_started(tab, resource))
        web.connect("load-changed", lambda view, event: self.page_loaded(tab, event))
        web.connect("load-failed", lambda view, event, uri, error: self.load_failed(tab))
        web.connect("decide-policy", lambda view, decision, kind: self.decide_policy(tab, decision, kind))

        self.apply_security_to_tab(tab)
        self.tab_list.select_row(row)

    def switch_tab(self, _box, row):
        if row is None:
            return
        self.active = next((tab for tab in self.tabs if tab["row"] is row), None)
        if not self.active:
            return
        self.tab_stack.set_visible_child(self.active["stack"])
        if self.content_stack.get_visible_child_name() == "browser":
            self.update_uri(self.active)
            self.update_loading(self.active)
            self.update_navigation()
            self.net_label.set_text(self.active["network"])

    def close_tab(self, tab):
        if len(self.tabs) == 1:
            self.new_tab()
        if self.active is tab:
            replacement = next(item for item in self.tabs if item is not tab)
            self.tab_list.select_row(replacement["row"])
        self.tab_list.remove(tab["row"])
        self.tab_stack.remove(tab["stack"])
        self.tabs.remove(tab)

    def update_title(self, tab):
        tab["label"].set_text((tab["web"].get_title() or "New Tab")[:35])

    def update_uri(self, tab):
        if tab is self.active:
            uri = tab["web"].get_uri()
            self.url.set_text(uri or "")

    def update_navigation(self):
        if self.active:
            web = self.active["web"]
            self.back.set_sensitive(web.can_go_back())
            self.forward.set_sensitive(web.can_go_forward())
        else:
            self.back.set_sensitive(False)
            self.forward.set_sensitive(False)

    def show_home(self):
        if not self.active:
            return
        self.content_stack.set_visible_child_name("browser")
        self.settings_button.remove_css_class("active")
        self.settings_open = False
        self.active["stack"].set_visible_child_name("home")
        self.url.set_text("")
        self.update_navigation()
        self.status_bar.set_visible(False)

    def search_url(self, query):
        engine = self.config["search_engine"]
        template = self.SEARCH_ENGINES[engine]
        if template == "custom":
            template = self.config.get("custom_search_url", "").strip()
        if "{query}" not in template:
            return None
        parts = urlsplit(template)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return None
        return template.replace("{query}", quote_plus(query.strip()))

    def search(self, query, tab=None):
        query = query.strip()
        if not query:
            return
        target = tab or self.active
        uri = self.search_url(query)
        if not uri:
            self.load_label.set_text("Add a search URL with {query} in Settings")
            self.status_bar.set_visible(True)
            return
        target["stack"].set_visible_child_name("web")
        target["web"].load_uri(uri)
        if target is self.active:
            self.content_stack.set_visible_child_name("browser")
            self.url.set_text(uri)

    def load_address(self, entry):
        if not self.active:
            return
        text = entry.get_text().strip()
        if not text:
            return
        if text.startswith(("http://", "https://")):
            uri = text
        elif " " in text or "." not in text:
            self.search(text)
            return
        else:
            uri = "https://" + text
        self.active["stack"].set_visible_child_name("web")
        self.content_stack.set_visible_child_name("browser")
        self.active["web"].load_uri(uri)

    def toggle_load(self, *_args):
        if not self.active:
            return
        web = self.active["web"]
        if web.is_loading():
            web.stop_loading()
        else:
            web.reload()

    def apply_security_to_tab(self, tab):
        mode = self.config["security"]
        tab["web"].get_settings().set_enable_javascript(mode != "Strict")

    def apply_security(self):
        for tab in self.tabs:
            self.apply_security_to_tab(tab)

    def decide_policy(self, tab, decision, decision_type):
        if decision_type != WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        if self.config["security"] == "Low":
            return False
        try:
            uri = decision.get_navigation_action().get_request().get_uri()
        except AttributeError:
            return False
        if urlsplit(uri).scheme.lower() != "http":
            return False

        decision.ignore()
        if self.config["security"] == "Normal":
            message = "Warning: HTTP page — trying HTTPS"
        else:
            message = "Strict mode: HTTP blocked — trying HTTPS"
        if tab is self.active:
            self.load_label.set_text(message)
            self.status_bar.set_visible(True)

        secure_uri = "https://" + uri[len("http://"):]

        def upgrade():
            if tab in self.tabs:
                tab["web"].load_uri(secure_uri)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(upgrade)
        return True

    def add_history(self, tab):
        uri = tab["web"].get_uri() or ""
        if not uri.startswith(("http://", "https://")):
            return
        title = tab["web"].get_title() or uri
        self.history.execute(
            "INSERT INTO visits(title, url) VALUES (?, ?)", (title, uri)
        )
        self.history.commit()

    def show_history(self):
        # What the fuck is Anime girl hot foot , why the fuck dose that happen ?
        self.settings_button.remove_css_class("active")
        self.settings_open = False
        self.render_history()
        self.content_stack.set_visible_child_name("history")

    def build_history_page(self):
        page = self.box(True, 10)
        page.set_margin_top(18)
        page.set_margin_start(20)
        page.set_margin_end(20)
        header = self.box(False, 8)
        header.append(self.heading("History"))
        remove_all = Gtk.Button(label="Remove All History")
        remove_all.connect("clicked", self.remove_all_history)
        header.append(remove_all)
        page.append(header)
        self.history_items = self.box(True, 4)
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(self.history_items)
        scroll.set_vexpand(True)
        page.append(scroll)
        footer = Gtk.Label(label="May god help you brother")
        footer.set_halign(Gtk.Align.CENTER)
        footer.add_css_class("muted")
        page.append(footer)
        return page

    def render_history(self):
        self.clear_box(self.history_items)
        records = self.history.execute(
            "SELECT id, title, url, visited_at FROM visits ORDER BY id DESC"
        ).fetchall()
        if not records:
            self.history_items.append(Gtk.Label(label="No history yet."))
            return
        for record_id, title, uri, visited_at in records:
            row = Gtk.ListBoxRow()
            line = self.box(False, 8)
            open_button = Gtk.Button(label=f"{title or uri}\n{uri}")
            open_button.set_hexpand(True)
            open_button.set_halign(Gtk.Align.FILL)
            open_button.connect("clicked", lambda *_args, url=uri: self.open_history_url(url))
            delete_button = Gtk.Button(label="×")
            delete_button.set_tooltip_text("Delete this entry")
            delete_button.connect("clicked", lambda *_args, item_id=record_id: self.delete_history_item(item_id))
            line.append(open_button)
            line.append(delete_button)
            row.set_child(line)
            gesture = Gtk.GestureClick()
            gesture.set_button(Gdk.BUTTON_SECONDARY)
            gesture.connect(
                "pressed", lambda controller, count, x, y, item=row, item_id=record_id:
                self.history_context_menu(item, item_id, x, y)
            )
            row.add_controller(gesture)
            self.history_items.append(row)

    def history_context_menu(self, row, record_id, x, y):
        popover = Gtk.Popover()
        button = Gtk.Button(label="Delete history entry")
        button.connect("clicked", lambda *_: self.delete_history_item(record_id))
        popover.set_child(button)
        popover.set_parent(row)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.popup()

    def open_history_url(self, uri):
        if not self.active:
            self.new_tab()
        self.content_stack.set_visible_child_name("browser")
        self.active["stack"].set_visible_child_name("web")
        self.active["web"].load_uri(uri)

    def delete_history_item(self, record_id):
        self.history.execute("DELETE FROM visits WHERE id = ?", (record_id,))
        self.history.commit()
        self.render_history()

    def remove_all_history(self, *_args):
        self.history.execute("DELETE FROM visits")
        self.history.commit()
        self.render_history()

    def build_settings_page(self):
        page = self.box(True, 14)
        page.set_margin_top(18)
        page.set_margin_bottom(18)
        page.set_margin_start(22)
        page.set_margin_end(22)

        title = self.heading("Settings")
        page.append(title)

        layout_heading = Gtk.Label(label="Layout")
        layout_heading.set_xalign(0)
        page.append(layout_heading)
        layout_value = Gtk.Label(label="Vertical tabs · Left")
        layout_value.set_xalign(0)
        layout_value.add_css_class("muted")
        page.append(layout_value)

        search_heading = Gtk.Label(label="Search Engine")
        search_heading.set_xalign(0)
        page.append(search_heading)
        self.engine_dropdown = Gtk.DropDown.new_from_strings(list(self.SEARCH_ENGINES))
        self.engine_dropdown.set_selected(list(self.SEARCH_ENGINES).index(self.config["search_engine"]))
        self.engine_dropdown.connect("notify::selected", self.search_engine_changed)
        page.append(self.engine_dropdown)

        self.custom_search_entry = Gtk.Entry()
        self.custom_search_entry.set_placeholder_text(
            "https://example.com/search?q={query}"
        )
        self.custom_search_entry.set_text(self.config.get("custom_search_url", ""))
        self.custom_search_entry.connect("changed", self.custom_search_changed)
        self.custom_search_entry.set_visible(
            self.config["search_engine"] == "Add your search engine"
        )
        page.append(self.custom_search_entry)
        joke = Gtk.Label(label="Man are you here to add google ?  -- you better not to")
        joke.set_xalign(0)
        joke.add_css_class("muted")
        page.append(joke)

        appearance = Gtk.Label(label="Appearance")
        appearance.set_xalign(0)
        page.append(appearance)
        self.theme_dropdown = Gtk.DropDown.new_from_strings(self.THEMES)
        self.theme_dropdown.set_selected(self.THEMES.index(self.config["theme"]))
        self.theme_dropdown.connect("notify::selected", self.theme_changed)
        page.append(self.theme_dropdown)

        security = Gtk.Label(label="Security")
        security.set_xalign(0)
        page.append(security)
        self.security_dropdown = Gtk.DropDown.new_from_strings(self.SECURITY_MODES)
        self.security_dropdown.set_selected(self.SECURITY_MODES.index(self.config["security"]))
        self.security_dropdown.connect("notify::selected", self.security_changed)
        page.append(self.security_dropdown)
        security_note = Gtk.Label(
            label="Normal: JavaScript on, HTTP page navigation upgraded to HTTPS. "
                  "Strict: JavaScript off. Low: HTTP allowed."
        )
        security_note.set_xalign(0)
        security_note.set_wrap(True)
        security_note.add_css_class("muted")
        page.append(security_note)

        privacy = Gtk.Label(label="Cookies")
        privacy.set_xalign(0)
        page.append(privacy)
        clear_cookies = Gtk.Button(label="Clear all cookies")
        clear_cookies.set_halign(Gtk.Align.START)
        clear_cookies.connect("clicked", self.clear_all_cookies)
        manage_cookies = Gtk.Button(label="Manage Cookies")
        manage_cookies.set_halign(Gtk.Align.START)
        manage_cookies.connect("clicked", self.manage_cookies)
        page.append(clear_cookies)
        page.append(manage_cookies)

        about_button = Gtk.Button(label="About Free Browser")
        about_button.set_halign(Gtk.Align.START)
        about_button.connect("clicked", lambda *_: self.content_stack.set_visible_child_name("about"))
        page.append(about_button)

        scroll = Gtk.ScrolledWindow()
        scroll.set_child(page)
        scroll.set_vexpand(True)
        return scroll

    def toggle_settings(self, *_args):
        self.settings_open = not self.settings_open
        if self.settings_open:
            self.content_stack.set_visible_child_name("settings")
            self.settings_button.add_css_class("active")
        else:
            self.content_stack.set_visible_child_name("browser")
            self.settings_button.remove_css_class("active")

    def search_engine_changed(self, dropdown, _pspec):
        selected = dropdown.get_selected()
        name = list(self.SEARCH_ENGINES)[selected]
        self.config["search_engine"] = name
        self.custom_search_entry.set_visible(name == "Add your search engine")
        self.save_config()

    def custom_search_changed(self, entry):
        self.config["custom_search_url"] = entry.get_text().strip()
        self.save_config()

    def theme_changed(self, dropdown, _pspec):
        self.config["theme"] = self.THEMES[dropdown.get_selected()]
        self.save_config()
        self.apply_theme()

    def security_changed(self, dropdown, _pspec):
        self.config["security"] = self.SECURITY_MODES[dropdown.get_selected()]
        self.save_config()
        self.apply_security()

    def build_about_page(self):
        page = self.box(True, 12)
        page.set_margin_top(22)
        page.set_margin_start(22)
        page.set_margin_end(22)
        page.append(self.heading("About Free Browser"))
        license_label = Gtk.Label(label="This project uses the GNU General Public License v3.0.")
        license_label.set_xalign(0)
        page.append(license_label)
        license_button = Gtk.Button(label="GNU General Public License v3")
        license_button.set_halign(Gtk.Align.START)
        license_button.connect("clicked", lambda *_: self.open_gpl())
        page.append(license_button)
        warning = Gtk.Label(
            label="Warning : This Browser is still on beta 0.1 , i hope that you know that because the browser may be not fully secure , dose not support your fav website , or else"
        )
        warning.set_xalign(0)
        warning.set_wrap(True)
        warning.set_max_width_chars(90)
        page.append(warning)
        back_button = Gtk.Button(label="Back to Settings")
        back_button.set_halign(Gtk.Align.START)
        back_button.connect("clicked", lambda *_: self.content_stack.set_visible_child_name("settings"))
        page.append(back_button)
        return page

    def open_gpl(self):
        try:
            Gio.AppInfo.launch_default_for_uri(self.GPL_URL, None)
        except GLib.Error:
            self.open_history_url(self.GPL_URL)

    def cookie_list_clear(self):
        if self.cookie_list:
            self.clear_box(self.cookie_list)

    def manage_cookies(self, *_args):
        if self.cookie_window:
            self.cookie_window.present()
            self.refresh_cookies()
            return
        self.cookie_window = Gtk.Window(title="Manage Cookies", transient_for=self.window)
        self.cookie_window.set_default_size(520, 480)
        self.cookie_window.set_modal(True)
        self.cookie_list = self.box(True, 6)
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(self.cookie_list)
        scroll.set_vexpand(True)
        outer = self.box(True, 8)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        note = Gtk.Label(label="Cookie values are hidden because they may contain login tokens.")
        note.set_wrap(True)
        note.set_xalign(0)
        outer.append(note)
        outer.append(scroll)
        self.cookie_window.set_child(outer)
        self.cookie_window.connect("close-request", self.cookie_window_closed)
        self.cookie_window.present()
        self.refresh_cookies()

    def cookie_window_closed(self, *_args):
        self.cookie_window = None
        self.cookie_list = None
        return False

    def refresh_cookies(self):
        if self.cookie_list:
            self.cookie_list_clear()
            self.cookie_list.append(Gtk.Label(label="Loading cookies..."))
            self.cookie_manager.get_all_cookies(None, self.cookies_loaded)

    def cookies_loaded(self, manager, result):
        try:
            cookies = manager.get_all_cookies_finish(result)
        except GLib.Error as error:
            cookies = []
            failure = str(error)
        else:
            failure = ""
        if self.cookie_list is None:
            return
        self.cookie_list_clear()
        if failure:
            self.cookie_list.append(Gtk.Label(label=failure))
        elif not cookies:
            self.cookie_list.append(Gtk.Label(label="No cookies found."))
        else:
            for cookie in cookies:
                row = self.box(False, 8)
                name = cookie.get_name() or "(unnamed)"
                domain = cookie.get_domain() or "(unknown domain)"
                label = Gtk.Label(label=f"{name} · {domain}")
                label.set_xalign(0)
                label.set_hexpand(True)
                delete = Gtk.Button(label="Delete")
                delete.connect("clicked", lambda *_args, item=cookie: self.delete_cookie(item))
                row.append(label)
                row.append(delete)
                self.cookie_list.append(row)

    def delete_cookie(self, cookie):
        self.cookie_manager.delete_cookie(cookie, None, self.cookie_deleted)

    def cookie_deleted(self, manager, result):
        try:
            manager.delete_cookie_finish(result)
        except GLib.Error:
            pass
        if self.cookie_list is not None:
            self.refresh_cookies()

    def clear_all_cookies(self, *_args):
        self.cookie_manager.get_all_cookies(None, self.delete_all_cookies_loaded)

    def delete_all_cookies_loaded(self, manager, result):
        try:
            cookies = manager.get_all_cookies_finish(result)
        except GLib.Error as error:
            self.load_label.set_text("Cookie error: " + str(error))
            self.status_bar.set_visible(True)
            return
        if not cookies:
            self.load_label.set_text("No cookies to clear")
        else:
            self.cookie_delete_pending = len(cookies)
            for cookie in cookies:
                self.cookie_manager.delete_cookie(
                    cookie, None, self.one_cookie_cleared
                )
            return
        self.status_bar.set_visible(True)
        if self.cookie_list is not None:
            self.refresh_cookies()

    def one_cookie_cleared(self, manager, result):
        try:
            manager.delete_cookie_finish(result)
        except GLib.Error:
            pass
        self.cookie_delete_pending -= 1
        if self.cookie_delete_pending == 0:
            self.load_label.set_text("All cookies cleared")
            self.status_bar.set_visible(True)
            if self.cookie_list is not None:
                self.refresh_cookies()

    def update_loading(self, tab):
        if tab is not self.active:
            return
        if tab["web"].is_loading():
            self.status_bar.set_visible(True)
            self.load_stack.set_visible_child_name("loading")
            self.spinner.start()
            self.load_label.set_text("Loading")
        else:
            self.spinner.stop()
            self.load_stack.set_visible_child_name("reload")
            self.progress.set_fraction(0)
            self.load_label.set_text("Checking connection...")

    def update_progress(self, tab):
        if tab is self.active:
            self.progress.set_fraction(tab["web"].get_estimated_load_progress())

    def resource_started(self, tab, resource):
        tab["resource"] = resource.get_uri() or ""
        if not tab["pending"]:
            tab["pending"] = True
            GLib.timeout_add(120, self.show_resource, tab)

    def show_resource(self, tab):
        tab["pending"] = False
        if tab is self.active and tab["web"].is_loading() and tab["resource"]:
            parts = urlsplit(tab["resource"])
            self.load_label.set_text("Loading: " + (parts.netloc + parts.path)[:55])
        return GLib.SOURCE_REMOVE

    def page_loaded(self, tab, event):
        if event == WebKit.LoadEvent.STARTED:
            tab["probe_id"] += 1
            tab["resource"] = ""
            if tab is self.active:
                self.status_bar.set_visible(True)
                self.progress.set_fraction(0)
        elif event == WebKit.LoadEvent.FINISHED:
            self.add_history(tab)
            uri = tab["web"].get_uri()
            if uri:
                threading.Thread(
                    target=self.check_network,
                    args=(tab, uri, tab["probe_id"]),
                    daemon=True
                ).start()
            else:
                GLib.timeout_add(900, self.hide_status, tab)

    def load_failed(self, tab):
        GLib.timeout_add(900, self.hide_status, tab)
        return False

    def check_network(self, tab, uri, probe_id):
        try:
            result = connections.probe(uri)
            GLib.idle_add(self.show_network, tab, uri, probe_id, result)
        except Exception as error:
            GLib.idle_add(self.network_error, tab, str(error))

    def show_network(self, tab, uri, probe_id, result):
        if (tab not in self.tabs or tab["probe_id"] != probe_id
                or tab["web"].get_uri() != uri):
            return GLib.SOURCE_REMOVE
        if result["ok"]:
            message = f'Network: {result["status"]} · {result["latency_ms"]:.0f} ms'
        else:
            message = "Network: " + result["error"]
        tab["network"] = message
        if tab is self.active:
            self.net_label.set_text(message)
            GLib.timeout_add(1100, self.hide_status, tab)
        return GLib.SOURCE_REMOVE

    def network_error(self, tab, error):
        if tab in self.tabs:
            tab["network"] = "Network: " + error
            if tab is self.active:
                self.net_label.set_text(tab["network"])
                GLib.timeout_add(1100, self.hide_status, tab)
        return GLib.SOURCE_REMOVE

    def hide_status(self, tab):
        if tab is self.active and not tab["web"].is_loading():
            self.status_bar.set_visible(False)
        return GLib.SOURCE_REMOVE


browser_instance = None


def on_activate(app):
    global browser_instance
    if browser_instance is None:
        browser_instance = Browser(app)
    else:
        browser_instance.window.present()


app = Gtk.Application(application_id="org.FreedomFoundation.FreeBrowser")
app.connect("activate", on_activate)
app.run(None)
