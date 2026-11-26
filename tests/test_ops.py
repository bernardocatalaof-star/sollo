from datetime import date, datetime, timedelta

from app import ops
from app.models import GasBottle, GasLog, OpsPurchase, OpsSupply, OpsTask, SeasonTemplate
from app.ops_seed import seed_ops
from app.settings_store import set_setting

TODAY = date(2026, 11, 26)


def test_task_who_shows_contact_as_leo_talks_to():
    assert ops.task_who(OpsTask(owner="Leo", contact="Carlos")) == "Leo falar com Carlos"
    assert ops.task_who(OpsTask(owner="", contact="Carlos")) == "Leo falar com Carlos"
    assert ops.task_who(OpsTask(owner="Ben")) == "Ben"
    assert ops.task_who(OpsTask(owner="")) == "Por atribuir"


def test_completing_recurring_task_creates_next_occurrence(db_session):
    task = OpsTask(title="Limpar filtros", place="Casa técnica", owner="Ben", recurrence_months=6)
    db_session.add(task)
    db_session.commit()

    nxt = ops.complete_task(db_session, task, by="Ben", today=TODAY)

    assert task.status == "done" and task.done_by == "Ben" and task.done_at is not None
    assert nxt is not None
    assert nxt.status == "todo"
    assert nxt.due_date == date(2027, 5, 26)
    assert nxt.recurrence_months == 6 and nxt.owner == "Ben"


def test_completing_one_off_task_creates_nothing(db_session):
    task = OpsTask(title="Aparafusar gaveta")
    db_session.add(task)
    db_session.commit()
    assert ops.complete_task(db_session, task, today=TODAY) is None
    assert db_session.query(OpsTask).count() == 1


def test_reopen_task(db_session):
    task = OpsTask(title="x")
    db_session.add(task)
    db_session.commit()
    ops.complete_task(db_session, task, today=TODAY)
    ops.reopen_task(db_session, task)
    assert task.status == "todo" and task.done_at is None


def test_task_board_groups_by_place_and_puts_far_due_dates_under_later(db_session):
    db_session.add_all(
        [
            OpsTask(title="a", place="Geral"),
            OpsTask(title="b", place="Olivia", urgent=True),
            OpsTask(title="c", place="Olivia"),
            OpsTask(title="later", place="Santiago", due_date=TODAY + timedelta(days=90)),
            OpsTask(title="soon", place="Santiago", due_date=TODAY + timedelta(days=5)),
        ]
    )
    db_session.commit()

    board = ops.task_board(db_session, TODAY)

    assert [g.place for g in board.groups] == ["Olivia", "Santiago", "Geral"]
    assert [t.title for t in board.groups[0].tasks] == ["b", "c"]  # urgent first
    assert [t.title for t in board.later] == ["later"]
    assert board.open_count == 4 and board.urgent_count == 1


def test_task_board_filter_matches_owner_or_contact(db_session):
    db_session.add_all(
        [
            OpsTask(title="leo", owner="Leo"),
            OpsTask(title="carlos", owner="Leo", contact="Carlos"),
            OpsTask(title="ben", owner="Ben"),
        ]
    )
    db_session.commit()
    carlos = ops.task_board(db_session, TODAY, "Carlos")
    assert [t.title for g in carlos.groups for t in g.tasks] == ["carlos"]
    leo = ops.task_board(db_session, TODAY, "Leo")
    assert sorted(t.title for g in leo.groups for t in g.tasks) == ["carlos", "leo"]


def test_supply_low_adds_one_purchase_and_ok_removes_it(db_session):
    supply = OpsSupply(name="Papel de cozinha")
    db_session.add(supply)
    db_session.commit()

    ops.set_supply_level(db_session, supply, "low")
    ops.set_supply_level(db_session, supply, "out")  # no duplicate, but becomes urgent
    purchases = db_session.query(OpsPurchase).all()
    assert len(purchases) == 1
    assert purchases[0].item == "Papel de cozinha" and purchases[0].urgent

    ops.set_supply_level(db_session, supply, "ok")
    assert db_session.query(OpsPurchase).count() == 0


def test_buying_a_stock_item_resets_it_to_ok(db_session):
    supply = OpsSupply(name="Esponjas")
    db_session.add(supply)
    db_session.commit()
    ops.set_supply_level(db_session, supply, "low")
    purchase = db_session.query(OpsPurchase).one()

    ops.mark_bought(db_session, purchase)

    assert purchase.bought and supply.level == "ok"


def test_gas_empty_logs_duration_orders_and_full_clears_order(db_session):
    bottle = GasBottle(label="Botija 1", status="in_use", status_since=datetime(2026, 10, 1))
    db_session.add(bottle)
    db_session.commit()

    ops.set_gas_status(db_session, bottle, "empty", now=datetime(2026, 11, 20))

    log = db_session.query(GasLog).one()
    assert (log.emptied_at - log.started_at).days == 50
    order = db_session.query(OpsPurchase).filter_by(gas=True).one()
    assert order.urgent and not order.bought

    ops.set_gas_status(db_session, bottle, "full", now=datetime(2026, 11, 22))
    assert db_session.query(OpsPurchase).filter_by(gas=True).count() == 0


def test_gas_summary_estimates_run_out(db_session):
    db_session.add(GasLog(bottle_label="x", started_at=datetime(2026, 1, 1), emptied_at=datetime(2026, 3, 2)))
    db_session.add(GasBottle(label="B", status="in_use", status_since=datetime(2026, 11, 1)))
    db_session.commit()
    summary = ops.gas_summary(db_session)
    assert summary.avg_days == 60
    assert summary.runs_out_around == date(2026, 12, 31)
    assert summary.has_reserve is False


def test_season_due_in_reminder_months_until_activated(db_session):
    tpl = SeasonTemplate(key="inverno", name="Inverno", months="10,11", items="Barragem: Retirar SUP\nEdredon quente")
    db_session.add(tpl)
    db_session.commit()

    assert ops.seasons_due(db_session, date(2026, 9, 1)) == []
    assert ops.seasons_due(db_session, TODAY) == [tpl]

    created = ops.activate_season(db_session, tpl, TODAY)

    assert created == 2
    tasks = {t.title: t for t in db_session.query(OpsTask).all()}
    assert tasks["Retirar SUP"].place == "Barragem"
    assert tasks["Edredon quente"].place == "Ambas"
    assert tasks["Edredon quente"].source == "Inverno 2026"
    assert ops.seasons_due(db_session, TODAY) == []
    assert ops.seasons_due(db_session, date(2027, 10, 1)) == [tpl]  # back next year


def test_dismiss_season(db_session):
    tpl = SeasonTemplate(key="verao", name="Verão", months="5,6", items="x")
    db_session.add(tpl)
    db_session.commit()
    ops.dismiss_season(db_session, tpl, date(2027, 5, 3))
    assert ops.seasons_due(db_session, date(2027, 5, 3)) == []
    assert db_session.query(OpsTask).count() == 0


def test_message_for_contact_is_addressed_to_them(db_session):
    db_session.add(OpsTask(title="Arranjar portão", place="Geral", owner="Leo", contact="Carlos"))
    db_session.commit()
    text = ops.build_message(db_session, "Carlos", today=TODAY)
    assert text.startswith("Olá Carlos!")
    assert "- Arranjar portão" in text


def test_message_for_leo_lists_who_to_call(db_session):
    db_session.add_all(
        [
            OpsTask(title="Rever loiças", place="Ambas", owner="Leo"),
            OpsTask(title="Revisão gás", place="Olivia", owner="Leo", contact="Azinheirinha"),
            OpsTask(title="Ben's", place="Olivia", owner="Ben"),
        ]
    )
    db_session.commit()
    text = ops.build_message(db_session, "Leo", today=TODAY)
    assert "- Rever loiças" in text
    assert "- Azinheirinha: Revisão gás" in text
    assert "Ben's" not in text


def test_cleaning_extra_lines_include_tasks_and_checklist(db_session):
    db_session.add(OpsTask(title="Destruir ninhos", place="Santiago", owner="Limpeza", urgent=True))
    db_session.commit()
    set_setting(db_session, ops.CLEANING_CHECKLIST_KEY, "Lanterna na caixa\n\nAC ligado")
    lines = ops.cleaning_extra_lines(db_session, TODAY)
    assert "* Santiago: Destruir ninhos (urgente)" in lines
    assert "* Lanterna na caixa" in lines and "* AC ligado" in lines


def test_seed_runs_once(db_session):
    assert seed_ops(db_session, today=TODAY) is True
    tasks = db_session.query(OpsTask).count()
    assert tasks > 20
    # papel de cozinha + esponjas were reported low, so they're on the list
    stock_purchases = db_session.query(OpsPurchase).filter(OpsPurchase.supply_id.isnot(None)).count()
    assert stock_purchases == 2
    assert db_session.query(SeasonTemplate).count() == 2
    assert seed_ops(db_session, today=TODAY) is False
    assert db_session.query(OpsTask).count() == tasks
