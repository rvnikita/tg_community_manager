from src.admin_log import admin_log
import src.db_helper as db_helper

def get_user_mention(user_id: int) -> str:
    with db_helper.session_scope() as db_session:

        user = db_session.query(db_helper.User).filter_by(id=user_id).first()

        if user is None:
            return str(user_id)
        else:
            # This lines was written by GPT-4 to generate desirable output for different user input combinations:
            # Output table for different user input combinations:
            #   First name | Last name | Username   | ID   | `user_mention`
            # --------------|-----------|------------|------|------------------------------
            #   "Nikita"    | "Rvachev" | "rvnikita" | 123  | "Nikita Rvachev - @rvnikita"
            #   "Nikita"    | "Rvachev" | None       | 123  | "Nikita Rvachev"
            #   None        | None      | "rvnikita" | 123  | "@rvnikita"
            #   "Nikita"    | None      | "rvnikita" | 123  | "Nikita - @rvnikita"
            #   None        | "Rvachev" | "rvnikita" | 123  | "Rvachev - @rvnikita"
            #   "Nikita"    | None      | None       | 123  | "Nikita"
            #   None        | "Rvachev" | None       | 123  | "Rvachev"
            #   None        | None      | None       | 123  | "123"
            return ', '.join(filter(bool, [
                f"{user.first_name} {user.last_name} - @{user.username}" if user.first_name and user.last_name and user.username else f"{user.first_name} {user.last_name}" if user.first_name and user.last_name else f"@{user.username}" if user.username else str(
                    user.id)]))