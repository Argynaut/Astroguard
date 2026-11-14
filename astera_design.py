"""Astera's shared macOS-inspired presentation layer. No remote assets required."""

from __future__ import annotations

from urllib.parse import quote


SYSTEM_FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "Segoe UI", sans-serif'

# Streamlit's React Aria calendar follows the browser locale by default. Use its
# document-scoped locale bootstrap so this English app also has English calendars
# and accessibility labels. Streamlit explicitly passes navigator.language to
# these widgets, so normalize it in this document only. No browser or OS
# preferences are written; navigation away restores the browser's normal locale.
ENGLISH_LOCALE = """<script>
(() => {
    const asteraLocale = Symbol.for("react-aria.i18n.locale");
    if (window[asteraLocale] !== "en-US") {
        window[asteraLocale] = "en-US";
        Object.defineProperty(navigator, "language", {value: "en-US", configurable: true});
        Object.defineProperty(navigator, "languages", {value: ["en-US"], configurable: true});
        document.documentElement.lang = "en";
        window.dispatchEvent(new Event("languagechange"));
    }
})();
</script>"""

PALETTES = {
    "Light": {
        "scheme": "light", "background": "#f5f5f7", "surface": "#ffffff",
        "inset": "#f8f8fa", "field": "#fbfbfc", "sidebar": "rgba(234,235,239,.88)",
        "toolbar": "rgba(245,245,247,.88)", "text": "#1d1d1f", "secondary": "#6e6e73",
        "tertiary": "#7c7c82", "accent": "#007aff", "accent_soft": "#e8f1ff",
        "line": "#e5e5e9", "grid": "#eeeeF1", "control_border": "#d8d8dd",
        "green": "#248a3d", "green_soft": "#edf7ef", "orange": "#a96000",
        "orange_soft": "#fff5e5", "red": "#d12432", "red_soft": "#fff0f1",
        "chart_secondary": "#8795ad", "selection": "#d8e6fb",
        "shadow": "0 2px 10px rgba(25,25,30,.025), 0 .5px 1.5px rgba(25,25,30,.07)",
        "control_shadow": "0 1px 2px rgba(0,0,0,.07)",
    },
    "Dark": {
        "scheme": "dark", "background": "#1c1c1e", "surface": "#2c2c2e",
        "inset": "#252527", "field": "#353537", "sidebar": "rgba(36,36,39,.92)",
        "toolbar": "rgba(28,28,30,.88)", "text": "#f5f5f7", "secondary": "#aeaeb2",
        "tertiary": "#98989f", "accent": "#0a84ff", "accent_soft": "#163451",
        "line": "#3a3a3d", "grid": "#3a3a3d", "control_border": "#4a4a4e",
        "green": "#63d37b", "green_soft": "#22392a", "orange": "#ffb340",
        "orange_soft": "#3d3222", "red": "#ff7b83", "red_soft": "#40282c",
        "chart_secondary": "#9baecb", "selection": "#30465e",
        "shadow": "0 2px 10px rgba(0,0,0,.08), 0 .5px 1px rgba(0,0,0,.22)",
        "control_shadow": "0 1px 2px rgba(0,0,0,.16)",
    },
}


# Original, simple line drawings. Using inline SVG keeps the app fully offline.
ICON_PATHS = {
    "astera": '<path d="M12 3c.9 5.1 3.9 8.1 9 9-5.1.9-8.1 3.9-9 9-.9-5.1-3.9-8.1-9-9 5.1-.9 8.1-3.9 9-9Z"/><path d="m18 3 .6 2.4L21 6l-2.4.6L18 9l-.6-2.4L15 6l2.4-.6Z"/>',
    "overview": '<rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1.5"/><rect x="14" y="3.5" width="6.5" height="6.5" rx="1.5"/><rect x="3.5" y="14" width="6.5" height="6.5" rx="1.5"/><rect x="14" y="14" width="6.5" height="6.5" rx="1.5"/>',
    "symptoms": '<path d="M20.4 5.4a5 5 0 0 0-7.1 0L12 6.7l-1.3-1.3a5 5 0 0 0-7.1 7.1L12 21l8.4-8.5a5 5 0 0 0 0-7.1Z"/><path d="M4 12h4l2-4 3.2 8 1.8-4h5"/>',
    "log": '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "profile": '<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "emergency": '<path d="m10.3 4-8 14a2 2 0 0 0 1.7 3h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0Z"/><path d="M12 9v5M12 17v.1"/>',
    "hr": '<path d="M20.4 5.4a5 5 0 0 0-7.1 0L12 6.7l-1.3-1.3a5 5 0 0 0-7.1 7.1L12 21l8.4-8.5a5 5 0 0 0 0-7.1Z"/>',
    "bp": '<path d="M4 13h4l3-7 3 13 3-6h3"/>',
    "temp": '<path d="M9 14.5V5a3 3 0 0 1 6 0v9.5a5 5 0 1 1-6 0Z"/><path d="M12 8v9"/><circle cx="12" cy="18" r="1.3"/>',
    "spo2": '<path d="M12 3c-2 3.2-7 8.2-7 12a7 7 0 0 0 14 0c0-3.8-5-8.8-7-12Z"/><path d="M8.5 15.5a3.5 3.5 0 0 0 3.5 3"/>',
    "sleep": '<path d="M20.5 14.2A8.8 8.8 0 0 1 9.8 3.5a8.8 8.8 0 1 0 10.7 10.7Z"/>',
    "activity": '<path d="m9 20 3-6-4-3 3-5 4 4h4M5 15l3-4M12 14l4 6"/><circle cx="14.5" cy="3.5" r="1.5"/>',
    "stress": '<circle cx="12" cy="12" r="9"/><path d="M8 14.5s1.5 2 4 2 4-2 4-2M8 9h.1M16 9h.1"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "link": '<path d="M5.6 7a9 9 0 0 1 12.8 0M8.5 10a5 5 0 0 1 7 0M11 13a1.4 1.4 0 0 1 2 0M12 16v5"/>',
    "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "arrow": '<path d="M5 12h14m-5-5 5 5-5 5"/>',
}


def palette(appearance: str = "Light") -> dict[str, str]:
    return PALETTES.get(appearance, PALETTES["Light"])


def icon(name: str, size: int = 20) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
            + ICON_PATHS[name] + '</svg>')


def stylesheet(appearance: str = "Light") -> str:
    colors = palette(appearance)
    variables = ";".join(f"--{key.replace('_', '-')}:{value}" for key, value in colors.items())
    nav_icons = {"nav_Dashboard": "overview", "nav_Symptom_Check": "symptoms", "nav_Health_Log": "log",
                 "nav_Profile": "profile", "new_profile": "plus", "emergency_shortcut": "emergency"}
    masks = []
    for key, name in nav_icons.items():
        uri = "data:image/svg+xml," + quote(icon(name))
        masks.append(f'.st-key-{key} button::before {{-webkit-mask-image:url("{uri}");mask-image:url("{uri}");}}')
    return '<style>:root{' + variables + f';color-scheme:{colors["scheme"]};--system-font:{SYSTEM_FONT}' + '}\n' + CSS + '\n' + '\n'.join(masks) + '</style>'


CSS = r"""
/* Application shell */
html, body, .stApp {background:var(--background);color:var(--text);font-family:var(--system-font);-webkit-font-smoothing:antialiased;}
.stApp {font-size:14px;}
.stApp, [data-testid="stMain"] {background:var(--background);}
[data-testid="stAppViewContainer"] {background:transparent;}
[data-testid="stMainBlockContainer"] {max-width:1400px;padding:0 40px 28px;}
[data-testid="stHeader"] {height:0;background:transparent;pointer-events:none;}
[data-testid="stToolbar"] {height:0;padding:0;pointer-events:none;}
[data-testid="stToolbarActions"], [data-testid="stAppDeployButton"], [data-testid="stMainMenu"], [data-testid="stDecoration"] {display:none;}
[data-testid="stExpandSidebarButton"] {position:fixed;top:17px;left:12px;z-index:101;pointer-events:auto;background:var(--surface);color:var(--secondary);border-radius:7px;width:28px;height:28px;}
.stApp:has([data-testid="stExpandSidebarButton"]) .statusbar .toolbar-title {margin-left:30px;}
[data-testid="stSidebarCollapsedControl"] {top:17px;left:12px;z-index:101;}
[data-testid="stSidebarCollapsedControl"] button {background:var(--surface);color:var(--secondary);border-radius:7px;}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {gap:20px;}
[data-testid="stElementContainer"]:has(.statusbar) {position:sticky;top:0;z-index:90;}
[data-testid="stElementContainer"]:has(.stHtml > style),
[data-testid="stElementContainer"]:has(.stHtml > script) {display:none;}
.statusbar {display:flex;align-items:center;justify-content:space-between;gap:20px;min-height:66px;margin:0 -40px 10px;padding:0 40px;background:var(--toolbar);border-bottom:1px solid var(--line);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);font-size:12px;color:var(--secondary);}
.toolbar-leading,.status-right {display:flex;align-items:center;gap:18px;min-width:0;}
.toolbar-title {font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;}
.toolbar-context {overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.toolbar-divider {height:16px;width:1px;flex:none;background:var(--control-border);}
.toolbar-link {display:flex;align-items:center;gap:7px;white-space:nowrap;color:var(--tertiary);}
.connection-state {white-space:nowrap;display:flex;align-items:center;gap:6px;}
.connection-state .dot {margin:0;}
.dot {display:inline-block;height:5px;width:5px;flex:none;border-radius:50%;margin:0 5px 1px 0;}

/* The sidebar is a source list, with utilities below the navigation. */
[data-testid="stSidebar"] {background:var(--sidebar);border-right:1px solid var(--line);backdrop-filter:blur(30px);-webkit-backdrop-filter:blur(30px);min-width:244px;max-width:264px;}
[data-testid="stSidebarContent"] {background:transparent;padding:0!important;}
[data-testid="stSidebarHeader"] {height:28px;min-height:28px;padding:5px 12px 0;margin:0;}
[data-testid="stSidebarUserContent"] {padding:0 16px 18px!important;}
[data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] {gap:6px;min-height:calc(100dvh - 48px);}
[data-testid="stSidebarCollapseButton"] button {color:var(--tertiary);}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {font-size:11px;color:var(--secondary);font-weight:500;}
.brand {display:flex;align-items:center;gap:11px;margin:5px 7px 24px;}
.brand-mark {display:grid;place-items:center;color:var(--accent);width:34px;height:34px;flex:none;}
.brand-name {font-size:25px;line-height:1.15;letter-spacing:-1px;font-weight:650;color:var(--text);}
.brand-subtitle {font-size:10px;line-height:1.4;color:var(--secondary);margin-top:4px;}
.sidebar-heading {font-size:11px;font-weight:600;color:var(--secondary);padding:16px 10px 10px;margin-bottom:8px;line-height:1.5;}
[data-testid="stSidebar"] .stButton button {justify-content:flex-start;text-align:left;width:100%;min-height:36px;padding:7px 11px;border-radius:7px;border:0!important;gap:10px;box-shadow:none;font-size:13px;font-weight:450;}
[data-testid="stSidebar"] .stButton button::before {content:"";width:18px;height:18px;flex:none;background:currentColor;mask-position:center;mask-repeat:no-repeat;mask-size:contain;-webkit-mask-position:center;-webkit-mask-repeat:no-repeat;-webkit-mask-size:contain;}
[data-testid="stSidebar"] .stButton button > div {justify-content:flex-start;}
[data-testid="stSidebar"] .stButton button[kind="tertiary"] {background:transparent;color:var(--secondary);}
[data-testid="stSidebar"] .stButton button[kind="tertiary"]:hover {background:var(--selection);color:var(--text);}
[data-testid="stSidebar"] .stButton button[kind="primary"] {background:var(--accent)!important;color:#fff!important;box-shadow:0 1px 3px #007aff18;}
[data-testid="stSidebar"] .stButton button[kind="primary"] p {color:#fff!important;font-weight:550;}
.st-key-new_profile button {min-height:29px!important;font-size:12px!important;color:var(--secondary)!important;}
[data-testid="stSidebarUserContent"] [data-testid="stLayoutWrapper"]:has(> .st-key-sidebar_utilities) {margin-top:auto;}
.st-key-sidebar_utilities {padding-top:28px;gap:11px;}
.mission-card {padding:15px 13px;background:var(--surface);border-radius:10px;box-shadow:var(--shadow);font-size:12px;line-height:1.7;color:var(--secondary);margin-bottom:13px;}
.mission-card .small-label {margin-bottom:6px;font-size:10px;font-weight:500;color:var(--secondary);}
.mission-card strong {display:block;font-size:13px;font-weight:600;color:var(--text);}
.mission-day {font-size:11px;margin-top:3px;}
.st-key-emergency_shortcut button {color:var(--red)!important;background:var(--red-soft)!important;margin-top:8px;}
.st-key-emergency_shortcut button:hover {filter:brightness(.98);}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {font-size:10px;line-height:1.6;color:var(--tertiary);}
.sidebar-footnote {font-size:9px;color:var(--tertiary);line-height:1.65;padding:6px 9px 0;}
.st-key-appearance [data-testid="stWidgetLabel"] p {font-size:11px;}
.st-key-appearance button {font-size:11px!important;min-height:27px!important;}

/* A compact system type scale, with quiet metadata. */
h1,h2,h3,h4,h5,h6 {font-family:var(--system-font)!important;color:var(--text);}
h1 {font-size:30px!important;font-weight:650!important;letter-spacing:-1.05px;line-height:1.2!important;padding:0 0 6px!important;}
h2 {font-size:20px!important;font-weight:600!important;letter-spacing:-.45px;padding:7px 0 6px!important;}
h3 {font-size:16px!important;font-weight:600!important;letter-spacing:-.25px;padding:3px 0 7px!important;}
p,li,label,[data-testid="stMarkdownContainer"] {font-family:var(--system-font);font-size:13px;line-height:1.6;}
[data-testid="stCaptionContainer"] p {color:var(--secondary);font-size:12px;line-height:1.6;}
[data-testid="stWidgetLabel"] p {font-size:12px;color:var(--secondary);line-height:1.4;}
[data-testid="stHeadingWithActionElements"] a {color:var(--tertiary);}
.small-label {font-size:13px;font-weight:600;letter-spacing:-.15px;color:var(--text);margin-bottom:12px;line-height:1.4;}
.eyebrow {color:var(--secondary);font-size:11px;font-weight:500;}
a {color:var(--accent);}
::selection {background:var(--selection);}

/* Native controls, including menus and calendar surfaces outside the main tree. */
button, input, textarea, select {font-family:var(--system-font)!important;}
input,textarea {caret-color:var(--accent);font-size:13px!important;}
input::placeholder,textarea::placeholder {color:var(--tertiary)!important;opacity:.85;}
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"] {background:var(--field)!important;color:var(--text)!important;border-color:var(--control-border)!important;border-radius:7px!important;}
[data-baseweb="select"] > div {background:var(--field)!important;color:var(--text)!important;border-color:var(--control-border)!important;border-radius:7px!important;}
[data-baseweb="select"] input,[data-baseweb="input"] input,[data-baseweb="textarea"] textarea {background:transparent!important;color:var(--text)!important;}
[data-baseweb="select"] svg {color:var(--secondary);}
[data-baseweb="input"]:focus-within,[data-baseweb="textarea"]:focus-within,[data-baseweb="select"] > div:focus-within {border-color:var(--accent)!important;box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 18%,transparent)!important;}
[data-testid="stNumberInput"] button {color:var(--secondary);background:transparent;border:0;border-radius:4px;}
[data-testid="stNumberInput"] button:hover {background:var(--inset);color:var(--text);}
[data-baseweb="popover"] > div,[data-baseweb="menu"],[role="listbox"] {background:var(--surface)!important;color:var(--text)!important;border-radius:9px!important;box-shadow:0 6px 28px #00000018;}
[role="option"] {color:var(--text)!important;background:transparent!important;font-size:13px;}
[role="option"]:hover,[role="option"][aria-selected="true"] {background:var(--accent-soft)!important;color:var(--accent)!important;}
[data-baseweb="tag"] {background:var(--accent-soft);color:var(--accent);border-radius:5px;}
[data-baseweb="calendar"] {background:var(--surface);color:var(--text);font-family:var(--system-font);}
button[kind="secondary"],button[kind="tertiary"],button[kind="primary"],button[kind="secondaryFormSubmit"],button[kind="primaryFormSubmit"] {min-height:33px;border-radius:7px;padding:5px 13px;font-size:12px;font-weight:500;transition:background .15s ease,box-shadow .15s ease;}
button[kind="secondary"],button[kind="secondaryFormSubmit"] {background:var(--surface);color:var(--text);border:1px solid var(--control-border);box-shadow:var(--control-shadow);}
button[kind="secondary"]:hover,button[kind="secondaryFormSubmit"]:hover {background:var(--inset);color:var(--text);border-color:var(--control-border);}
button[kind="primary"],button[kind="primaryFormSubmit"] {background:var(--accent)!important;color:#fff!important;border:1px solid transparent!important;box-shadow:var(--control-shadow);}
button[kind="primary"]:hover,button[kind="primaryFormSubmit"]:hover {filter:brightness(1.05);}
button[kind="primary"] p,button[kind="primaryFormSubmit"] p {color:#fff!important;}
button p {font-size:12px!important;line-height:1.4!important;color:inherit;}
button[kind="tertiary"] {background:transparent;border-color:transparent;color:var(--secondary);}
button:focus-visible,summary:focus-visible,[role="tab"]:focus-visible {outline:3px solid color-mix(in srgb,var(--accent) 40%,transparent)!important;outline-offset:3px;}
button:disabled {opacity:.42;cursor:default;filter:none!important;}
[data-testid="stButtonGroup"] [role="radiogroup"], [data-testid="stButtonGroup"] [role="group"] {display:inline-flex;gap:2px;background:var(--line);padding:3px;border-radius:8px;}
button[data-variant="segmented_control"] {border:0!important;border-radius:5px!important;background:transparent!important;color:var(--secondary)!important;min-height:28px;padding:4px 11px;font-size:12px;box-shadow:none;}
button[data-variant="segmented_control"][aria-checked="true"] {background:var(--surface)!important;color:var(--text)!important;box-shadow:0 1px 4px #00000015;}
button[data-variant="segmented_control"] p {color:inherit!important;white-space:nowrap;}
[data-testid="stCheckbox"] label p {font-size:12px;color:var(--secondary);}
[data-testid="stCheckbox"] input {accent-color:var(--accent);}
[data-testid="stTabs"] [role="tablist"] {gap:4px;border-bottom:1px solid var(--line);padding-bottom:9px;}
[data-testid="stTabs"] [role="tab"] {border:0;border-radius:6px;min-height:31px;padding:5px 14px;color:var(--secondary);}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {background:var(--surface);color:var(--text);box-shadow:var(--shadow);}
[data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"], [data-testid="stTabs"] .react-aria-SelectionIndicator {display:none;}

/* Shared cards and grouped settings. */
.st-key-trend_panel,.st-key-ground_panel,.st-key-data_used,.st-key-recommendations,.st-key-causes,.st-key-findings,.st-key-profile_card,.st-key-baseline_form,.st-key-symptom_form,.st-key-log_filters,.st-key-log_records,.st-key-activity_records,.st-key-create_profile_shell {background:var(--surface);border:0;border-radius:13px;padding:22px 24px;box-shadow:var(--shadow);}
.st-key-trend_panel > [data-testid="stVerticalBlock"], .st-key-symptom_form > [data-testid="stVerticalBlock"] {gap:15px;}
.st-key-recommendations {min-height:240px;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-color:var(--line)!important;border-radius:12px;}
[data-testid="stLayoutWrapper"]:has(> [data-testid="stVerticalBlock"][style*="border"]) {border-color:var(--line);}
[data-testid="stForm"] {background:var(--surface);border:0!important;border-radius:13px;padding:24px;box-shadow:var(--shadow);}
[data-testid="stExpander"] {background:var(--surface);border:0!important;border-radius:10px;box-shadow:var(--shadow);}
[data-testid="stExpander"] details {border:0!important;border-radius:10px;}
[data-testid="stExpander"] summary {min-height:43px;padding:11px 16px;color:var(--secondary);font-size:12px;}
[data-testid="stExpander"] summary:hover {color:var(--text);background:var(--inset);border-radius:10px;}
[data-testid="stExpander"] summary p {font-size:12px;}
[data-testid="stExpander"] [data-testid="stForm"] {padding:2px 1px 8px;box-shadow:none;}
[data-testid="stExpanderDetails"] {padding:4px 19px 18px;}
[data-testid="stAlert"] {border:0;border-radius:10px;font-size:12px;padding:13px 17px;}
[data-testid="stAlert"] p {font-size:12px;}
[data-testid="stDialog"] [role="dialog"] {border:1px solid var(--line);border-radius:15px;background:var(--surface);color:var(--text);box-shadow:0 18px 70px #0000002b;}
.st-key-delete_profile button,.st-key-confirm_profile_deletion button,.st-key-clear_baseline button {color:var(--red);}
.st-key-confirm_profile_deletion button {background:var(--red)!important;color:#fff;}

/* Health overview */
.deviation-banner {display:flex;align-items:center;gap:13px;padding:16px 20px;background:var(--surface);border-radius:12px;box-shadow:var(--shadow);}
.summary-icon {width:32px;height:32px;border-radius:50%;display:grid;place-items:center;flex:none;background:var(--accent-soft);color:var(--accent);}
.deviation-banner .small-label {font-size:11px;font-weight:500;color:var(--secondary);margin:0 0 4px;}
.deviation-banner strong {color:var(--text);font-size:13px;font-weight:550;}
.deviation-banner.warning .summary-icon {background:var(--orange-soft);color:var(--orange);}
.metrics-grid {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin:16px 0 14px;}
.metric-card {padding:18px 17px 15px;background:var(--surface);border-radius:12px;box-shadow:var(--shadow);position:relative;min-width:0;}
.metric-title {display:flex;align-items:center;gap:5px;justify-content:space-between;color:var(--secondary);font-size:11px;font-weight:500;}
.metric-symbol {color:var(--tertiary);height:20px;display:flex;align-items:center;}
.metric-value {font-size:clamp(22px,1.9vw,29px);font-weight:600;letter-spacing:-1.2px;color:var(--text);line-height:1.3;margin:16px 0 8px;white-space:nowrap;font-variant-numeric:tabular-nums;}
.metric-value small {font-size:11px;font-weight:450;letter-spacing:0;color:var(--secondary);}
.metric-baseline {font-size:10px;color:var(--tertiary);white-space:normal;}
.metric-status {font-size:10px;margin-top:10px;white-space:normal;}
.chart-heading {display:flex;align-items:center;gap:8px;}
.chart-heading svg {color:var(--accent);}
.chart-subtitle {font-size:11px;font-weight:400;color:var(--secondary);margin-top:4px;}
.js-plotly-plot .plotly .modebar {display:none!important;}
.wellbeing-card {background:var(--surface);border-radius:12px;padding:20px 22px;box-shadow:var(--shadow);min-height:132px;}
.wellbeing-heading {display:flex;align-items:center;gap:8px;font-size:11px;color:var(--secondary);font-weight:500;}
.wellbeing-heading svg {color:var(--tertiary);}
.wellbeing-value {font-size:27px;font-weight:600;letter-spacing:-.8px;line-height:1.3;margin:11px 0 6px;color:var(--text);font-variant-numeric:tabular-nums;}
.wellbeing-note {font-size:11px;color:var(--tertiary);}

/* Symptom check and assessment */
.emergency-note {display:flex;align-items:center;gap:12px;padding:14px 17px;border-radius:10px;background:var(--red-soft);color:var(--secondary);font-size:12px;line-height:1.6;}
.emergency-note svg {color:var(--red);flex:none;}
.emergency-note strong {color:var(--red);font-weight:550;}
.chat-prompt {padding:20px 22px;background:var(--surface);border-radius:12px;box-shadow:var(--shadow);font-size:14px;line-height:1.7;color:var(--secondary);margin:0 0 10px;}
.chat-prompt strong {font-weight:550;color:var(--text);}
.data-row {display:flex;justify-content:space-between;gap:14px;padding:12px 0;border-bottom:1px solid var(--line);font-size:11px;color:var(--secondary);}
.data-row strong {color:var(--text);text-align:right;font-size:12px;font-weight:500;overflow-wrap:anywhere;min-width:0;}
.data-row:last-of-type {border-bottom:0;}
.severity-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;}
.severity-card {display:flex;align-items:center;gap:6px;background:var(--surface);color:var(--tertiary);border-radius:10px;padding:17px 16px;font-size:11px;min-height:58px;box-shadow:var(--shadow);}
.severity-card.active {font-weight:600;box-shadow:var(--shadow),inset 0 0 0 1.5px currentColor;}
.recommendation {display:flex;gap:14px;padding:15px 0;line-height:1.7;font-size:13px;border-bottom:1px solid var(--line);}
.recommendation:last-child {border:0;padding-bottom:2px;}
.recommendation > span {display:grid;place-items:center;width:24px;height:24px;border-radius:50%;background:var(--accent-soft);color:var(--accent);font-size:11px;line-height:1;flex:none;font-weight:550;margin-top:1px;}
.recommendation.emergency > span {background:var(--red-soft);color:var(--red);}
.cause {padding:13px 0;border-bottom:1px solid var(--line);font-size:12px;line-height:1.6;color:var(--text);}
.cause:last-child {border:0;}
.cause small {display:block;font-size:11px;line-height:1.6;color:var(--secondary);margin-top:5px;}
.cause-badge {float:right;font-size:9px;font-weight:500;color:var(--secondary);background:var(--inset);padding:2px 7px;border-radius:4px;margin-left:8px;}
.finding {font-size:12px;line-height:1.7;padding:9px 0;color:var(--secondary);}
.finding.deviation {color:var(--orange);}
.queue-count {font-size:29px;font-weight:600;letter-spacing:-1px;color:var(--text);font-variant-numeric:tabular-nums;}
.queue-count.pending {color:var(--orange);}

/* Profile, history and empty states */
.profile-header {display:flex;align-items:center;gap:18px;padding:4px 0 27px;}
.profile-header h2 {margin:0;padding:0!important;font-size:24px!important;font-weight:600;overflow-wrap:anywhere;}
.profile-header p {margin:5px 0 0;color:var(--secondary);font-size:12px;overflow-wrap:anywhere;}
.profile-avatar {width:64px;height:64px;flex:none;border-radius:50%;background:var(--accent-soft);display:grid;place-items:center;color:var(--accent);font-size:22px;font-weight:500;letter-spacing:-.5px;}
.profile-fields {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:2px;margin:0 0 22px;border-radius:10px;background:var(--inset);overflow:hidden;}
.profile-fields > div {min-width:0;padding:17px 18px;}
.profile-fields dt {font-size:11px;color:var(--secondary);}
.profile-fields dd {margin:7px 0 0;font-size:14px;font-weight:500;color:var(--text);overflow-wrap:anywhere;}
.profile-baselines {grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:5px;}
.profile-baselines dd {font-size:18px;font-weight:550;letter-spacing:-.3px;}
.profile-baselines > div {padding:17px 15px;}
.empty-state {display:flex;flex-direction:column;align-items:center;text-align:center;padding:49px 25px 45px;}
.empty-state-icon {display:grid;place-items:center;width:48px;height:48px;margin-bottom:15px;border-radius:12px;background:var(--inset);color:var(--tertiary);}
.empty-state strong {font-size:15px;font-weight:550;color:var(--text);}
.empty-state p {max-width:390px;font-size:12px;color:var(--secondary);margin:8px 0 0;}
[data-testid="stDataFrame"] {border-radius:9px;overflow:hidden;border:1px solid var(--line);}
.table-fallback {max-height:420px;overflow:auto;border:1px solid var(--line);border-radius:9px;background:var(--surface);}
.table-fallback table {width:100%;border-collapse:separate;border-spacing:0;font-size:12px;color:var(--text);}
.table-fallback th,.table-fallback td {padding:13px 15px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line);}
.table-fallback th {position:sticky;top:0;background:var(--inset);color:var(--secondary);font-size:11px;font-weight:550;white-space:nowrap;}
.table-fallback td {min-width:85px;max-width:380px;overflow-wrap:anywhere;}
.table-fallback tr:nth-child(even) td {background:var(--inset);}
.table-fallback tr:last-child td {border-bottom:0;}
.step {color:var(--accent);font-size:11px;}

@media(min-width:1600px) {[data-testid="stMainBlockContainer"] {padding-left:56px;padding-right:56px;}.statusbar {margin-left:-56px;margin-right:-56px;padding-left:56px;padding-right:56px;}}
@media(max-width:1250px) {[data-testid="stMainBlockContainer"] {padding-left:27px;padding-right:27px;}.statusbar {margin-left:-27px;margin-right:-27px;padding-left:27px;padding-right:27px;}.metrics-grid {gap:9px;}.metric-card {padding:16px 12px 14px;}.metric-value {font-size:25px;}.metric-title {font-size:10px;}.metric-symbol svg {width:17px;height:17px;}.toolbar-link {max-width:230px;white-space:normal;font-size:10px;}.profile-baselines {grid-template-columns:repeat(3,minmax(0,1fr));}}
@media(max-width:1120px) {.toolbar-context {max-width:150px;}.status-right {gap:10px;}.toolbar-link {max-width:190px;}.metrics-grid {grid-template-columns:repeat(3,minmax(0,1fr));}.metric-title {font-size:11px;}.metric-value {font-size:28px;}.severity-grid {grid-template-columns:repeat(2,minmax(0,1fr));}.st-key-check_symptoms kbd {display:none;}}
@media(max-width:760px) {[data-testid="stMainBlockContainer"] {padding:0 18px 24px;}.statusbar {margin:0 -18px 6px;padding:0 18px;gap:12px;min-height:60px;}.toolbar-context,.toolbar-divider,.toolbar-link {display:none;}.status-right {font-size:10px;}h1 {font-size:27px!important;}.metrics-grid {grid-template-columns:repeat(2,minmax(0,1fr));}.metric-card {padding:17px;}.metric-card:last-child {grid-column:1/-1;}.metric-value {font-size:29px;}.profile-fields,.profile-baselines {grid-template-columns:repeat(2,minmax(0,1fr));}.st-key-trend_panel,.st-key-ground_panel,.st-key-data_used,.st-key-recommendations,.st-key-causes,.st-key-findings,.st-key-profile_card,.st-key-symptom_form,.st-key-log_filters,.st-key-log_records,.st-key-activity_records {padding:19px;}[data-testid="stForm"] {padding:19px;}.deviation-banner {padding:15px;}.statusbar .toolbar-title {margin-left:30px;}}
@media(prefers-reduced-motion:reduce) {*,*::before,*::after {transition:none!important;animation:none!important;scroll-behavior:auto!important;}}
"""
