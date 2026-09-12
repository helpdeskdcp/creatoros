import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.orchestrator import AIOrchestrator
from app.modules.scripts.models import Script, ScriptFormat, ScriptVersion
from app.modules.scripts.schemas import _GeneratedScript

SYSTEM_PROMPT = (
    "You are CreatorOS's Script Engine. Write a structured YouTube script "
    "outline with a hook, setup, promise, main points, examples, transitions, "
    "pattern interrupts, a call to action, and an ending. Match the requested "
    "format's length and pacing. Do not fabricate statistics or claims."
)

_FORMAT_DESCRIPTIONS = {
    ScriptFormat.SHORT: "a 30-60 second YouTube Short",
    ScriptFormat.FIVE_MIN: "a 5-minute video",
    ScriptFormat.TEN_MIN: "a 10-minute video",
    ScriptFormat.FIFTEEN_MIN: "a 15-minute video",
    ScriptFormat.LONG_FORM: "a 20+ minute long-form video",
}


async def generate_script(
    db: AsyncSession,
    orchestrator: AIOrchestrator,
    owner_user_id: uuid.UUID,
    title: str,
    topic_id: uuid.UUID | None,
    fmt: ScriptFormat,
    key_points: list[str],
) -> Script:
    script = Script(owner_user_id=owner_user_id, topic_id=topic_id, title=title, format=fmt)
    db.add(script)
    await db.flush()

    await _generate_version(db, orchestrator, script, fmt, key_points, version_number=1)
    await db.commit()
    result = await get_script(db, script.id)
    assert result is not None  # just committed above; only None if the row vanished mid-request
    return result


async def add_script_version(
    db: AsyncSession,
    orchestrator: AIOrchestrator,
    script: Script,
    key_points: list[str],
) -> Script:
    next_version = (max((v.version_number for v in script.versions), default=0)) + 1
    await _generate_version(db, orchestrator, script, script.format, key_points, next_version)
    await db.commit()
    result = await get_script(db, script.id)
    assert result is not None  # script already existed; only None if the row vanished mid-request
    return result


async def _generate_version(
    db: AsyncSession,
    orchestrator: AIOrchestrator,
    script: Script,
    fmt: ScriptFormat,
    key_points: list[str],
    version_number: int,
) -> ScriptVersion:
    user_prompt = (
        f"Video title: {script.title}\n"
        f"Format: {_FORMAT_DESCRIPTIONS[fmt]}\n"
        f"Key points to cover: {', '.join(key_points) if key_points else '(use your judgment)'}"
    )
    result: _GeneratedScript = await orchestrator.generate_structured(
        task="generate_script",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        schema=_GeneratedScript,
        max_tokens=3000,
    )

    full_text = "\n\n".join(
        [
            f"[HOOK]\n{result.hook}",
            f"[SETUP]\n{result.setup}",
            f"[PROMISE]\n{result.promise}",
            "[MAIN POINTS]\n" + "\n".join(f"- {p}" for p in result.main_points),
            "[EXAMPLES]\n" + "\n".join(f"- {e}" for e in result.examples),
            "[PATTERN INTERRUPTS]\n" + "\n".join(f"- {p}" for p in result.pattern_interrupts),
            f"[CTA]\n{result.cta}",
            f"[ENDING]\n{result.ending}",
        ]
    )

    version = ScriptVersion(
        script_id=script.id,
        version_number=version_number,
        hook=result.hook,
        setup=result.setup,
        promise=result.promise,
        main_points=json.dumps(result.main_points),
        examples=json.dumps(result.examples),
        transitions=json.dumps(result.transitions),
        pattern_interrupts=json.dumps(result.pattern_interrupts),
        cta=result.cta,
        ending=result.ending,
        full_text=full_text,
        generated_by="ai",
    )
    db.add(version)
    await db.flush()
    return version


async def get_script(db: AsyncSession, script_id: uuid.UUID) -> Script | None:
    return await db.scalar(
        select(Script).where(Script.id == script_id).options(selectinload(Script.versions))
    )


async def list_scripts(db: AsyncSession, owner_user_id: uuid.UUID) -> list[Script]:
    result = await db.scalars(
        select(Script)
        .where(Script.owner_user_id == owner_user_id)
        .options(selectinload(Script.versions))
        .order_by(Script.created_at.desc())
    )
    return list(result)
