"""Name addressing (voice.addressing): the seated driver's first name, now and then, never on the wrong message."""

from __future__ import annotations

from pitwall.voice.addressing import NameCaller, first_name, with_name
from pitwall.voice.types import MessageKind, Priority, RadioMessage


def msg(kind: MessageKind = MessageKind.RACE, text: str = "Up to P5.", *, addressable: bool = True,
        prio: Priority = Priority.NORMAL) -> RadioMessage:  # fmt: skip
    return RadioMessage("m", kind, prio, text, text.replace("P5", "P 5"), 0.0, meta={"addressable": addressable})


def test_with_name() -> None:
    assert with_name("Up to P5.", "Sam") == "Up to P5, Sam."
    assert with_name("Good move. P5.", "Sam") == "Good move, Sam. P5."
    assert with_name("Gap ahead 1.2s. Behind 0.8s.", "Sam") == "Gap ahead 1.2s, Sam. Behind 0.8s."  # not "1, Sam.2s"
    assert with_name("Up to P5", "Sam") == "Up to P5, Sam"
    # a first sentence with a comma or colon: the name first, never mid-sentence ("That lap, 1:15.576, James.")
    assert with_name("That lap, 1:15.576. Flashback used.", "James") == "James, that lap, 1:15.576. Flashback used."
    assert with_name("3 second penalty: cutting the track.", "James") == "James, 3 second penalty: cutting the track."
    assert with_name("P8 after lap one, up 3.", "Sam") == "Sam, P8 after lap one, up 3."
    assert with_name("Norris is pitting, P4.", "Sam") == "Sam, Norris is pitting, P4."  # a name keeps its capital
    assert with_name("Rolling start. You start 12th of 12.", "Sam") == "Rolling start, Sam. You start 12th of 12."


def test_first_name() -> None:
    assert first_name("Sam Reid") == "Sam" and first_name("Zoë") == "Zoë" and first_name("Jean-Luc P") == "Jean-Luc"
    for bad in (None, "", "Driver", "Driver 03", "driver", "R2D2", "A", "Player", "42"):
        assert first_name(bad) is None, bad


def test_addressable_messages_once_a_minute() -> None:
    c = NameCaller()
    c.set_driver("Sam Reid", True, seat_changed=False)
    out = c.apply(msg(), 100.0)
    assert (out.text, out.speech) == ("Up to P5, Sam.", "Up to P 5, Sam.")
    assert c.apply(msg(), 130.0).text == "Up to P5."  # within 60 s
    assert c.apply(msg(), 161.0).text == "Up to P5, Sam."
    assert c.apply(msg(addressable=False), 300.0).text == "Up to P5."


def test_the_first_proactive_message_after_a_seat_change_confirms_the_seat() -> None:
    c = NameCaller()
    c.set_driver("James", True, seat_changed=False)
    c.set_driver("Sam", True, seat_changed=True)
    assert c.apply(msg(MessageKind.ANSWER, "Fuel is fine.", addressable=False), 0.0).text == "Fuel is fine."
    assert c.apply(msg(MessageKind.STRATEGY, "Box this lap.", addressable=False), 1.0).text == "Box this lap, Sam."
    assert c.apply(msg(MessageKind.STRATEGY, "Stay out.", addressable=False), 200.0).text == "Stay out."  # once


def test_never_on_urgent_cue_answer_control_or_validation_or_when_off() -> None:
    c = NameCaller()
    c.set_driver("Sam", True, seat_changed=True)
    for kind in (MessageKind.CUE, MessageKind.ANSWER, MessageKind.CONTROL, MessageKind.VALIDATION):
        assert c.apply(msg(kind), 0.0).text == "Up to P5.", kind
    assert c.apply(msg(MessageKind.ALERT, "Red flag.", prio=Priority.URGENT), 0.0).text == "Red flag."
    off = NameCaller()
    off.set_driver("Sam", False, seat_changed=True)
    assert off.apply(msg(), 0.0).text == "Up to P5."
    gone = NameCaller()
    gone.set_driver("Sam", True, seat_changed=False)
    gone.disable_name()  # the TTS engine would drop it
    assert gone.apply(msg(), 0.0).text == "Up to P5."
