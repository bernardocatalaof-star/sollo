"""One-time starting data for the operations pages, gathered on 26/11/2026
from the owners' WhatsApp group, the Notion "Revisão Outubro" task database
and the "Inverno" / "Summer experience" Notion pages.

Runs once per database (tracked by a Settings marker), so later edits and
deletions are never overwritten or reinstated.
"""

from datetime import date

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.models import GasBottle, OpsPurchase, OpsSupply, OpsTask, SeasonTemplate
from app.ops import CLEANING_CHECKLIST_KEY, OPS_SEED_KEY, set_supply_level
from app.settings_store import get_setting, set_setting

# (title, place, owner, contact, urgent, notes)
_TASKS = [
    # Sistema de água
    ("Trocar os filtros das bombas de água (estão muito mal)", "Casa técnica", "Ben", "", True, ""),
    ("Agendar análise à água e ajustar o tratamento se for preciso", "Geral", "Leo", "", True,
     "Houve um caso de intoxicação por água (Notion: Problemas últimos tempos)."),
    # Segurança
    ("Revisão do sistema de gás", "Olivia", "Leo", "Azinheirinha", True,
     "Houve queixa de cheiro a gás dentro da cabin."),
    ("Verificar detetores de fumo e monóxido de carbono (2 por cabin, a funcionar)", "Ambas", "Leo", "", True, ""),
    ("Arranjo aos blackouts", "Olivia", "Leo", "Paulo Linguiça", False, ""),
    # Santiago
    ("Destruir ninhos de abelhas no revestimento exterior, junto ao janelão", "Santiago", "Limpeza", "", True, ""),
    ("Trocar a luz exterior fundida", "Santiago", "Ben", "", False, ""),
    ("Luzes exteriores do caminho a pé", "Santiago", "Ben", "", False, ""),
    ("Verificar nível da água do esgoto e a causa dos entupimentos", "Santiago", "Ben", "", False, ""),
    ("Aparafusar gaveta", "Santiago", "Ben", "", False, ""),
    ("Trocar pilhas Shelly", "Santiago", "Ben", "", False, ""),
    ("Instalar router?", "Santiago", "Ben", "", False, ""),
    ("Escavar mais e aumentar a fossa", "Santiago", "Ben", "", False,
     "Comprar novo depósito, tubagens, carvão, enchimentos de filtragem."),
    ("Mudar localização da bomba de enchimento do depósito", "Santiago", "", "", False, ""),
    ("Nova sanita? (substituição)", "Santiago", "Leo", "", False, "Queixas de cheiro intenso da sanita."),
    ("Nova sinalética do caminho a pé", "Santiago", "Leo", "", False, ""),
    ("Folha de emergências na parede", "Santiago", "Leo", "", False, "Ver foto no WhatsApp de 25/11."),
    # Olivia
    ("Pintar chapa da salamandra", "Olivia", "Ben", "", False, ""),
    ("Pintar cabin (paredes, telhado, deck)", "Olivia", "Ben", "", False, "Lixar antes de pintar."),
    ("Arranjar relay", "Olivia", "Ben", "", False, ""),
    # Ambas
    ("Pôr batentes nas portas", "Ambas", "Ben", "", False, ""),
    ("Etiqueta com o PIN dos telemóveis (Nokia) por trás", "Ambas", "Leo", "", False,
     "Hóspedes não sabiam o PIN do Nokia da Santiago."),
    ("Colar etiquetas da salamandra e \"como aquecer a cabin\"", "Ambas", "Leo", "", False, ""),
    ("Colar etiquetas novas (shampoos, açúcar, etc.)", "Ambas", "Leo", "", False, ""),
    ("Botijas de água quente nas cabins", "Ambas", "Leo", "", False, ""),
    ("Rever loiças e jogos", "Ambas", "Leo", "", False, ""),
    ("Decidir a regra do AC no inverno e explicá-la no guia", "Ambas", "", "", False,
     "A recomendação 11h–15h não serve: é quando está mais calor (Ben, 23/11)."),
    # Geral
    ("Sinalética para as caixas: galochas, poncho e lanterna", "Geral", "Leo", "", False, ""),
    ("Verificar a lanterna e deixá-la carregada na caixa junto ao estacionamento", "Geral", "Leo", "", False, ""),
    ("Confirmar se o óleo das madeiras também serve para o chão", "Geral", "Leo", "", False, ""),
    ("Ligar o modem na casa técnica", "Casa técnica", "Ben", "", False,
     "As duas tomadas estão ocupadas (bomba de água e esquentador): precisa de ficha tripla."),
    ("Deixar 4 luzes suplentes", "Armazém", "Ben", "", False, ""),
    ("Recolher SUP e espreguiçadeiras", "Barragem", "Ben", "", False, ""),
    ("Reduzir calcário: colocar filtros", "Geral", "", "", False, ""),
]

# (title, place, owner, months, due_in_months, notes) -- due_in_months None = due now
_RECURRING = [
    ("Limpar os filtros das bombas de água", "Casa técnica", "Ben", 6, 6, ""),
    ("Análise à água", "Geral", "Leo", 12, 12, "Para ver se é preciso ajustar o tratamento."),
    ("Produto desentupidor / desengordurante nos ralos", "Ambas", "Ben", 3, None,
     "PRODUTO PERIGOSO. Só com a cabin vazia e algumas horas antes do próximo check-in; "
     "enxaguar bem com água. Luvas e óculos. Nunca misturar com lixívia nem outros produtos. "
     "Guardar fechado na casa técnica, nunca na cabin. Produto e dose: (preencher)."),
]

# (item, place, category, urgent, notes, linked task title)
_PURCHASES = [
    ("Filtros das bombas de água", "Casa técnica", "obra", True, "", "Trocar os filtros das bombas de água (estão muito mal)"),
    ("Cafeteira (+1 de reserva)", "Santiago", "cabin", False, "A cafeteira partiu; ter reserva na cabin.", None),
    ("Colheres pequenas", "Olivia", "cabin", False, "", None),
    ("Mobília exterior", "Santiago", "cabin", False,
     "No armazém ainda há 1 conjunto exterior (mesa + 2 cadeiras) e 1 espreguiçadeira.", None),
    ("Ficha tripla", "Casa técnica", "obra", False, "", "Ligar o modem na casa técnica"),
    ("Batentes de porta", "Ambas", "obra", False, "", "Pôr batentes nas portas"),
    ("Tinta Hammerite (spray)", "Olivia", "obra", False, "", "Pintar chapa da salamandra"),
    ("Nova mangueira exterior", "Olivia", "obra", False, "", None),
    ("Afixadores de etiquetas de parede", "Geral", "obra", False, "", None),
    ("Abraçadeiras 50 cm", "Geral", "obra", False, "", None),
    ("Conjunto de chaves inglesas pequenas", "Geral", "obra", False, "", None),
    ("Alicate pequeno", "Geral", "obra", False, "", None),
    ("Tiras mata-moscas", "Geral", "consumivel", False, "", None),
]

# Consumables that should never run out; (name, starting level)
_SUPPLIES = [
    ("Papel de cozinha", "low"),
    ("Esponjas da loiça", "low"),
    ("Shampoo / gel de banho", "ok"),
    ("Açúcar", "ok"),
    ("Lenha", "ok"),
    ("Aparas", "ok"),
    ("Pinhas", "ok"),
    ("Fósforos", "ok"),
    ("Acendalhas bio", "ok"),
    ("Pilhas", "ok"),
    ("Lâmpadas suplentes", "ok"),
]

_SEASONS = [
    (
        "inverno",
        "Inverno",
        "❄️",
        "10,11",
        "\n".join(
            [
                "Retirar BBQ exterior e guardar com capa",
                "Trocar por edredon quente",
                "Retirar o mapa até à barragem",
                "Repor experiência fogueira, salamandra e cozinhar no fogo",
                "Cesto com lenha, aparas, pinhas, fósforos e acendalhas bio",
                "Geral: Galochas na zona do estacionamento",
                "Geral: Lanterna na zona do estacionamento",
                "Geral: Alterar o texto dos emails para o inverno",
                "Barragem: Retirar prancha SUP e cadeiras",
            ]
        ),
    ),
    (
        "verao",
        "Verão",
        "☀️",
        "5,6",
        "\n".join(
            [
                "Barragem: Manta geotêxtil + brita",
                "Barragem: 2 espreguiçadeiras e prancha SUP",
                "Exterior: cama de rede, fairy lights, luzes pendentes, toldo, mesinha de apoio",
                "BBQ / fogão a gás com forno de pizza lá fora",
                "Cesto ou bolsa para levarem para a barragem",
                "Spray de hortelã e repelente de mosquitos",
                "Folheto \"Summer Experience\"",
                "Bebidas WhyNot no frigorífico",
                "Pôr o mapa até à barragem",
                "Trocar o edredon quente por um leve",
                "Geral: Fogo proibido — rever guia, etiquetas e emails",
                "Geral: Alterar o texto dos emails para o verão",
            ]
        ),
    ),
]

_CLEANING_CHECKLIST = "Lanterna carregada na caixa das galochas"


def seed_ops(db: Session, today: date | None = None) -> bool:
    """Returns True if it seeded (first run), False if already done before."""
    if get_setting(db, OPS_SEED_KEY):
        return False
    today = today or date.today()

    tasks_by_title: dict[str, OpsTask] = {}
    for title, place, owner, contact, urgent, notes in _TASKS:
        task = OpsTask(title=title, place=place, owner=owner, contact=contact, urgent=urgent, notes=notes)
        db.add(task)
        tasks_by_title[title] = task
    for title, place, owner, months, due_in, notes in _RECURRING:
        db.add(
            OpsTask(
                title=title,
                place=place,
                owner=owner,
                recurrence_months=months,
                due_date=today + relativedelta(months=due_in) if due_in else None,
                notes=notes,
            )
        )
    db.flush()

    for item, place, category, urgent, notes, task_title in _PURCHASES:
        task = tasks_by_title.get(task_title) if task_title else None
        db.add(
            OpsPurchase(
                item=item,
                place=place,
                category=category,
                urgent=urgent,
                notes=notes,
                task_id=task.id if task else None,
            )
        )

    supplies = []
    for position, (name, _level) in enumerate(_SUPPLIES):
        supply = OpsSupply(name=name, level="ok", position=position)
        db.add(supply)
        supplies.append(supply)
    db.add(GasBottle(label="Botija 1", status="check", position=0))
    db.add(GasBottle(label="Botija 2", status="check", position=1))

    for key, name, icon, months, items in _SEASONS:
        if not db.query(SeasonTemplate).filter_by(key=key).first():
            db.add(SeasonTemplate(key=key, name=name, icon=icon, months=months, items=items))
    db.commit()

    for supply, (_name, level) in zip(supplies, _SUPPLIES):
        if level != "ok":
            set_supply_level(db, supply, level, by="WhatsApp 25/11")

    if not get_setting(db, CLEANING_CHECKLIST_KEY):
        set_setting(db, CLEANING_CHECKLIST_KEY, _CLEANING_CHECKLIST)
    set_setting(db, OPS_SEED_KEY, today.isoformat())
    return True
