from __future__ import annotations

from . import db
from .models import Clue, Spectrum
from .moderation import normalize_clue_text

SPECTRUMS = [
    ("Good", "Bad", "General", "medium"),
    ("Highly addictive", "Mildly addictive", "General", "medium"),
    ("Cold", "Hot", "General", "medium"),
    ("Weird", "Normal", "General", "medium"),
    ("Colorful", "Colorless", "General", "medium"),
    ("High calorie", "Low calorie", "General", "medium"),
    ("Feels good", "Feels bad", "General", "medium"),
    ("Essential", "Inessential", "General", "medium"),
    ("Expensive", "Cheap", "General", "medium"),
    ("Overrated weapon", "Underrated weapon", "General", "medium"),
    ("Common", "Rare", "General", "medium"),
    ("Sexy", "Unsexy", "General", "medium"),
    ("Hard subject", "Easy subject", "General", "medium"),
    ("Famous", "Unknown", "General", "medium"),
    ("Easy to use", "Difficult to use", "General", "medium"),
    ("Wired", "Tired", "General", "medium"),
    ("Clean", "Dirty", "General", "medium"),
    ("Requires skill", "Requires luck", "General", "medium"),
    ("Flavorful", "Flavorless", "General", "medium"),
    ("Fascinating topic", "Boring topic", "General", "medium"),
    ("Good actor", "Bad actor", "General", "medium"),
    ("Hipster", "Basic", "General", "medium"),
    ("Safe job", "Dangerous job", "General", "medium"),
    ("Sci-Fi", "Fantasy", "General", "medium"),
    ("Formal", "Casual", "General", "medium"),
    ("Overpaid", "Underpaid", "General", "medium"),
    ("Wet", "Dry", "General", "medium"),
    ("Overrated skill", "Underrated skill", "General", "medium"),
    ("Encouraged", "Forbidden", "General", "medium"),
    ("Happy song", "Sad song", "General", "medium"),
    ("Durable", "Fragile", "General", "medium"),
    ("Dork", "Geek", "General", "medium"),
    ("Evil", "Good", "General", "medium"),
    ("Best day of the year", "Worst day of the year", "General", "medium"),
    ("Good habit", "Bad habit", "General", "medium"),
    ("Dog person", "Cat person", "General", "medium"),
    ("Openly love", "Guilty pleasure", "General", "medium"),
    ("Talented", "Untalented", "General", "medium"),
    ("Light", "Dark", "General", "medium"),
    ("Overrated actor", "Underrated actor", "General", "medium"),
    ("Easy to find", "Hard to find", "General", "medium"),
    ("Beautiful man", "Ugly man", "General", "medium"),
    ("Easy to remember", "Hard to remember", "General", "medium"),
    ("Highbrow", "Lowbrow", "General", "medium"),
    ("Healthy", "Unhealthy", "General", "medium"),
    ("Good man", "Bad man", "General", "medium"),
    ("Historically irrelevant", "Historically important", "General", "medium"),
    ("Hairy", "Hairless", "General", "medium"),
    ("Flexible", "Inflexible", "General", "medium"),
    ("Exotic pet", "Normal pet", "General", "medium"),
    ("Extrovert", "Introvert", "General", "medium"),
    ("Movie was better", "Book was better", "General", "medium"),
    ("Good movie", "Bad movie", "General", "medium"),
    ("Beautiful", "Ugly", "General", "medium"),
    ("Happens suddenly", "Happens slowly", "General", "medium"),
    ("Career", "Job", "General", "medium"),
    ("Hated", "Loved", "General", "medium"),
    ("The Dark Side of the Force", "The Light Side of the Force", "General", "medium"),
    ("Good pizza topping", "Bad pizza topping", "General", "medium"),
    ("Utopia", "Dystopia", "General", "medium"),
    ("Immature person", "Mature person", "General", "medium"),
    ("Overrated thing to own", "Underrated thing to own", "General", "medium"),
    ("Nice person", "Mean person", "General", "medium"),
    ("Adventure movie", "Action movie", "General", "medium"),
    ("Believable", "Unbelievable", "General", "medium"),
    ("Classy", "Trashy", "General", "medium"),
    ("Permanent", "Temporary", "General", "medium"),
    ("Doesn't look like a person", "Looks like a person", "General", "medium"),
    ("Tastes good", "Tastes bad", "General", "medium"),
    ("Game", "Sport", "General", "medium"),
    ("Cool", "Uncool", "General", "medium"),
    ("Greatest living person", "Worst living person", "General", "medium"),
    ("Overrated", "Underrated", "General", "medium"),
    ("Clean food", "Messy food", "General", "medium"),
    ("Ethical", "Unethical", "General", "medium"),
    ("Good gift", "Bad gift", "General", "medium"),
    ("Fashionable", "Unfashionable", "General", "medium"),
    ("Forgiveable", "Unforgiveable", "General", "medium"),
    ("Harmful", "Harmless", "General", "medium"),
    ("Hygienic", "Unhygienic", "General", "medium"),
    ("Good music", "Bad music", "General", "medium"),
    ("Useful", "Useless", "General", "medium"),
    ("Work of art", "Trash", "General", "medium"),
    ("Important", "Unimportant", "General", "medium"),
    ("Hard to spell", "Easy to spell", "General", "medium"),
    ("Virtue", "Vice", "General", "medium"),
    ("Overrated musician", "Underrated musician", "General", "medium"),
    ("Popular activity", "Unpopular activity", "General", "medium"),
    ("Whole", "Divided", "General", "medium"),
    ("Reliable", "Unreliable", "General", "medium"),
    ("Hard to kill", "Easy to kill", "General", "medium"),
    ("Stable", "Unstable", "General", "medium"),
    ("Pointy animal", "Round animal", "General", "medium"),
    ("Good TV show", "Bad TV show", "General", "medium"),
    ("Traditionally feminine", "Traditionally masculine", "General", "medium"),
    ("Useful body part", "Useless body part", "General", "medium"),
    ("Classic", "Fad", "General", "medium"),
    ("Brilliant", "Stupid", "General", "medium"),
    ("Strong", "Weak", "General", "medium"),
    ("Useful invention", "Useless invention", "General", "medium"),
    ("Conservative", "Liberal", "General", "medium"),
    ("Popular", "Unpopular", "General", "medium"),
    ("Enemy", "Friend", "General", "medium"),
    ("Exciting", "Boring", "General", "medium"),
    ("Smelly in a good way", "Smelly in a bad way", "General", "medium"),
    ("Hero", "Villain", "General", "medium"),
    ("Overrated thing to do", "Underrated thing to do", "General", "medium"),
    ("Useful in an emergency", "Useless in an emergency", "General", "medium"),
    ("For adults", "For kids", "General", "medium"),
    ("Hard to do", "Easy to do", "General", "medium"),
    ("Priceless", "Worthless", "General", "medium"),
    ("Nurture", "Nature", "General", "medium"),
    ("Democracy", "Dictatorship", "General", "medium"),
    ("Weird greeting", "Normal greeting", "General", "medium"),
    ("Cat name", "Dog name", "General", "medium"),
    ("Partisan", "Non-partisan", "General", "medium"),
    ("Infinite", "Limited", "General", "medium"),
    ("Formal event", "Casual event", "General", "medium"),
    ("Good investment", "Bad investment", "General", "medium"),
    ("Heavy topic", "Small talk", "General", "medium"),
    ("Spicy", "Mild", "General", "medium"),
    ("Sacrilegious", "Religious", "General", "medium"),
    ("Art", "Not art", "General", "medium"),
    ("Prohibited", "Illegal", "General", "medium"),
    ("Elitist", "Popular", "General", "medium"),
    ("In control", "Out of control", "General", "medium"),
    ("Loud", "Quiet", "General", "medium"),
    ("Public knowledge", "Secret", "General", "medium"),
    ("Too big", "Too small", "General", "medium"),
    ("Long", "Short", "General", "medium"),
    ("Best year in history", "Worst year in history", "General", "medium"),
    ("Capitalist", "Socialist", "General", "medium"),
    ("Well known fact", "Little known fact", "General", "medium"),
    ("Mobile", "Stationary", "General", "medium"),
    ("Global issue", "Local issue", "General", "medium"),
    ("Skill", "Talent", "General", "medium"),
    ("Best era to time travel", "Worst era to time travel", "General", "medium"),
    ("The best", "The worst", "General", "medium"),
    ("Large number", "Small number", "General", "medium"),
    ("False", "True", "General", "medium"),
    ("Avant garde", "Old fashioned", "General", "medium"),
    ("Beautiful word", "Ugly word", "General", "medium"),
    ("Tiny", "Small", "General", "medium"),
    ("Natural", "Unnatural", "General", "medium"),
    ("Phony person", "Genuine person", "General", "medium"),
    ("Original", "Derivative", "General", "medium"),
    ("Sexy color", "Unsexy color", "General", "medium"),
    ("Benefits everyone", "Benefits you", "General", "medium"),
    ("Powerful", "Powerless", "General", "medium"),
    ("Vapes", "Doesn't vape", "General", "medium"),
    ("Vegetable", "Fruit", "General", "medium"),
    ("Pseudoscience", "Science", "General", "medium"),
    ("Serious topic", "Funny topic", "General", "medium"),
    ("Firm", "Limp", "General", "medium"),
    ("News", "Gossip", "General", "medium"),
    ("Easy to sit on", "Hard to sit on", "General", "medium"),
    ("Too much", "Not enough", "General", "medium"),
    ("Vertical", "Horizontal", "General", "medium"),
    ("Scented", "Unscented", "General", "medium"),
    ("Not huggable", "Huggable", "General", "medium"),
    ("Homogenous", "Heterogeneous", "General", "medium"),
    ("Exclusive", "Inclusive", "General", "medium"),
    ("Commerce", "Art", "General", "medium"),
    ("Pop icon", "One hit wonder", "General", "medium"),
    ("Good advice", "Bad advice", "General", "medium"),
    ("Good candy", "Bad candy", "General", "medium"),
    ("Radical", "Traditional", "General", "medium"),
    ("Good mouthfeel", "Bad mouthfeel", "General", "medium"),
    ("Legal", "Illegal", "General", "medium"),
    ("Shallow thought", "Deep thought", "General", "medium"),
    ("Good school", "Bad school", "General", "medium"),
    ("Always on time", "Never on time", "General", "medium"),
    ("Will live to 100", "Won't live to 100", "General", "medium"),
    ("Good Disney character", "Bad Disney character", "General", "medium"),
    ("Good world leader", "Bad world leader", "General", "medium"),
    ("Strange", "Weird", "General", "medium"),
    ("Infamous", "Famous", "General", "medium"),
    ("Most powerful god", "Least powerful god", "General", "medium"),
    ("Fun person", "Boring person", "General", "medium"),
    ("Overrated book", "Underrated book", "General", "medium"),
    ("Best chore", "Worst chore", "General", "medium"),
    ("Overpopulated species", "Endangered species", "General", "medium"),
    ("Green", "Blue", "General", "medium"),
    ("Terrifying", "Thrilling", "General", "medium"),
    ("Unexpected", "Expected", "General", "medium"),
    ("Person who'd beat you up", "Person you could beat up", "General", "medium"),
    ("Overrated game", "Underrated game", "General", "medium"),
    ("You don't want your parents to watch you do it", "You want your parents to watch you do it", "General", "medium"),
    ("Evil", "Good", "General", "medium"),
    ("Jock", "Nerd", "General", "medium"),
]

# Entries are (left_label, right_label, clue_text, target_position).
SEED_CLUES: list[tuple[str, str, str, int]] = []

ACTIVE_SPECTRUM_PAIRS = {(left, right) for left, right, _, _ in SPECTRUMS}


def suppress_removed_seed_spectrums() -> None:
    """Deactivate seed-catalog spectrums that were removed from SPECTRUMS.

    The game treats the seed list as the source of truth for available
    spectrums. When a pair is deleted from SPECTRUMS later, existing local
    databases may still contain that spectrum and clues attached to it. Rather
    than hard-deleting rows that other tables may reference, this soft-deletes
    the spectrum and its clues by flipping their is_active flags so prompts,
    leaderboards, history, and stats can consistently suppress them.
    """
    removed_spectrums = [
        spectrum
        for spectrum in Spectrum.query.filter_by(is_active=True).all()
        if (spectrum.left_label, spectrum.right_label) not in ACTIVE_SPECTRUM_PAIRS
    ]
    if not removed_spectrums:
        return

    removed_spectrum_ids = [spectrum.id for spectrum in removed_spectrums]
    for spectrum in removed_spectrums:
        spectrum.is_active = False

    Clue.query.filter(
        Clue.spectrum_id.in_(removed_spectrum_ids),
        Clue.is_active.is_(True),
    ).update({Clue.is_active: False}, synchronize_session=False)


def seed_if_empty() -> None:
    if Spectrum.query.first() is not None:
        suppress_removed_seed_spectrums()
        db.session.commit()
        return

    spectra_by_pair = {}
    for left, right, category, difficulty in SPECTRUMS:
        spectrum = Spectrum(
            left_label=left,
            right_label=right,
            category=category,
            difficulty=difficulty,
            is_active=True,
        )
        db.session.add(spectrum)
        spectra_by_pair[(left, right)] = spectrum

    db.session.flush()

    for left, right, text, target in SEED_CLUES:
        spectrum = spectra_by_pair.get((left, right))
        if spectrum is None:
            continue
        db.session.add(
            Clue(
                spectrum_id=spectrum.id,
                author_user_id=None,
                text=text,
                normalized_text=normalize_clue_text(text),
                target_position=float(target),
                is_seed=True,
                is_active=True,
            )
        )

    db.session.commit()
