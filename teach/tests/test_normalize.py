from hermes_teach.events import BROWSER, KEY_DOWN, KEY_UP, MOUSE_DOWN, MOUSE_UP, SCROLL, WINDOW, RawEvent, Target
from hermes_teach.normalize import normalize
from hermes_teach.recorder.desktop import canonical_key


def kd(t, key, char=None, **extra):
    return RawEvent(t, KEY_DOWN, {"key": key, "char": char, **extra}, Target(window_title="App"))


def ku(t, key):
    return RawEvent(t, KEY_UP, {"key": key})


def typed(t0, text):
    out = []
    for i, ch in enumerate(text):
        out += [kd(t0 + i * 0.01, ch.lower(), ch), ku(t0 + i * 0.01 + 0.005, ch.lower())]
    return out


def click(t, x, y, button="left"):
    tgt = Target(x=x, y=y, window_title="App", off_x=x - 10, off_y=y - 10)
    return [RawEvent(t, MOUSE_DOWN, {"button": button}, tgt), RawEvent(t + 0.05, MOUSE_UP, {"button": button}, tgt)]


def test_typing_merges_into_one_step_and_backspace_edits():
    evs = click(0, 50, 50) + typed(1, "Helo") + [kd(1.1, "backspace"), ku(1.11, "backspace")] + typed(1.2, "lo")
    steps = normalize(evs)
    assert [s.action for s in steps] == ["click", "type"]
    assert steps[1].text == "Hello"


def test_hotkey_with_windows_control_char_and_special_keys():
    evs = typed(0, "ab") + [kd(1, "ctrl"), kd(1.01, "s", "s"), ku(1.02, "s"), ku(1.03, "ctrl"),
                            kd(2, "enter"), ku(2.01, "enter")]
    steps = normalize(evs)
    assert [(s.action, s.keys) for s in steps] == [("type", []), ("hotkey", ["ctrl", "s"]), ("key", ["enter"])]


def test_canonical_key_maps_windows_ctrl_chars():
    class K:  # pynput KeyCode lookalike
        def __init__(self, char, vk=None):
            self.char, self.vk = char, vk
    assert canonical_key(K("\x13")) == ("s", "s")
    assert canonical_key(K(None, 0x41)) == ("a", "a")
    assert canonical_key(K("Ą")) == ("ą", "Ą")


def test_altgr_polish_letters_stay_text():
    evs = [kd(0, "ctrl"), kd(0.01, "alt"), kd(0.02, "ą", "ą"), ku(0.03, "ą"), ku(0.04, "alt"), ku(0.05, "ctrl"),
           kd(0.1, "alt_gr"), kd(0.11, "ę", "ę"), ku(0.12, "ę"), ku(0.13, "alt_gr")]
    steps = normalize(evs)
    assert [(s.action, s.text) for s in steps] == [("type", "ąę")]


def test_double_click_and_drag():
    tgt_a = Target(x=100, y=100)
    tgt_b = Target(x=300, y=140)
    evs = click(0, 20, 20) + click(0.2, 21, 21) + [
        RawEvent(1, MOUSE_DOWN, {"button": "left"}, tgt_a), RawEvent(1.5, MOUSE_UP, {"button": "left"}, tgt_b)]
    steps = normalize(evs)
    assert steps[0].action == "click" and steps[0].count == 2
    assert steps[1].action == "drag" and (steps[1].dx, steps[1].dy) == (200, 40)


def test_scroll_merges_and_window_focus():
    w1 = Target(window_title="Editor")
    evs = [RawEvent(0, WINDOW, {}, w1), RawEvent(0.1, WINDOW, {}, Target(window_title="Browser")),
           RawEvent(1, SCROLL, {"dx": 0, "dy": -1}, Target(x=1, y=1, window_title="Browser")),
           RawEvent(1.1, SCROLL, {"dx": 0, "dy": -2}, Target(x=1, y=1, window_title="Browser"))]
    steps = normalize(evs)
    assert [s.action for s in steps] == ["focus", "scroll"]   # quick double switch collapses
    assert steps[0].target.window_title == "Browser"
    assert steps[1].dy == -3


def test_sensitive_keys_are_never_kept():
    evs = typed(0, "joe") + [kd(1, "tab"), ku(1.01, "tab")] + [
        kd(2 + i / 100, "masked", "•", sensitive=True) for i in range(6)]
    steps = normalize(evs)
    assert [(s.action, s.text, s.sensitive) for s in steps] == [
        ("type", "joe", False), ("key", "", False), ("type", "", True)]


def test_browser_fills_collapse_and_navigation_after_click_is_dropped():
    sel = Target(selector="#q", url="http://x/")
    evs = [RawEvent(0, BROWSER, {"op": "navigate"}, Target(url="http://x/")),
           RawEvent(1, BROWSER, {"op": "fill", "value": "a"}, sel),
           RawEvent(1.1, BROWSER, {"op": "fill", "value": "ab"}, sel),
           RawEvent(2, BROWSER, {"op": "click"}, Target(selector="button:has-text(\"Go\")")),
           RawEvent(2.2, BROWSER, {"op": "navigate"}, Target(url="http://x/result"))]
    steps = normalize(evs)
    assert [(s.action, s.text) for s in steps] == [("browser.goto", ""), ("browser.fill", "ab"), ("browser.click", "")]
