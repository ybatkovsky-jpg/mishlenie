"""FSM states for the trainer conversation flow."""

from aiogram.fsm.state import State, StatesGroup


class TrainerStates(StatesGroup):
    """Main conversation states."""

    # Phase 0: Onboarding
    sphere_selection = State()
    thinking_interest = State()

    # Phase 1: Diagnostics (7 questions, one per thinking type)
    diagnostics_q1 = State()  # Аналитическое
    diagnostics_q2 = State()  # Логическое
    diagnostics_q3 = State()  # Критическое
    diagnostics_q4 = State()  # Системное
    diagnostics_q5 = State()  # Стратегическое
    diagnostics_q6 = State()  # Креативное
    diagnostics_q7 = State()  # Эмоциональный интеллект
    profile_display = State()  # Show profile, choose next step

    # Phase 2: Training — deep dive into a thinking type
    training_choice = State()  # Choose thinking type or combined
    training_task = State()  # Task displayed, waiting for mindfulness

    # Phase 3: Feedback — user answered
    awaiting_answer = State()  # Waiting for user's answer
    feedback_view = State()  # Showing feedback, asking deepening question
    retrieval_checkin = State()  # Retrieval practice: user recalls key principles

    # Phase 4: Combined tasks
    combined_task = State()
    combined_answer = State()

    # Phase 5: Mindfulness
    mindfulness_break = State()
    mindfulness_checkin = State()


class DiagnosticsData:
    """Temporary storage for diagnostics answers (passed via FSM data)."""

    def __init__(self) -> None:
        self.current_q: int = 0
        self.answers: list[str] = []
        self.sphere: str = "общее развитие"
        self.current_thinking_type: str | None = None
        self.current_task: str | None = None
        self.difficulty: int = 0  # 0=начальный, 1=средний, 2=продвинутый
