"""The question gate and the job lock of the one api process."""

import threading
import time

from app.api.limits import QuestionGate, one_job


def test_questions_beyond_the_limit_wait_in_order_and_go_on_when_a_place_frees():
    gate = QuestionGate(lambda: 1, poll_seconds=0.01)
    assert gate.enter(lambda: None, lambda: False) is False
    order, waits = [], []

    def ask(name):
        if gate.enter(lambda: waits.append(name), lambda: False) is not None:
            order.append(name)
            gate.leave()

    threads = [threading.Thread(target=ask, args=(name,)) for name in ("b", "c")]
    for thread in threads:
        thread.start()
        time.sleep(0.05)
    assert waits == ["b", "c"] and order == []
    gate.leave()
    for thread in threads:
        thread.join(2)
    assert order == ["b", "c"] and gate.running == 0


def test_a_waiting_question_whose_client_left_gives_up_its_place():
    gate = QuestionGate(lambda: 1, poll_seconds=0.01)
    gate.enter(lambda: None, lambda: False)
    assert gate.enter(lambda: None, lambda: True) is None
    gate.leave()
    assert gate.enter(lambda: None, lambda: False) is False


def test_a_raised_limit_lets_the_next_question_in():
    limit = [1]
    gate = QuestionGate(lambda: limit[0], poll_seconds=0.01)
    gate.enter(lambda: None, lambda: False)
    limit[0] = 2
    assert gate.enter(lambda: None, lambda: False) is False and gate.running == 2


def test_a_sync_a_compile_and_an_eval_never_overlap_and_a_nested_job_keeps_its_lock():
    inside, overlaps = [0], []

    def job():
        with one_job():
            inside[0] += 1
            overlaps.append(inside[0])
            with one_job():
                time.sleep(0.01)
            inside[0] -= 1

    threads = [threading.Thread(target=job) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    assert overlaps == [1, 1, 1]
