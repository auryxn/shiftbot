from aiogram.fsm.state import State, StatesGroup

class JobForm(StatesGroup):
    title = State(); description = State(); hourly_rate = State(); hours = State(); date = State(); arrival_time = State(); address = State(); required_workers = State()
    preview = State()

class WorkerNameForm(StatesGroup):
    full_name = State()
