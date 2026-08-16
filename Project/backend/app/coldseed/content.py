"""Hand-curated content pools for the cold seed (app/coldseed/build.py).

Deliberately not Faker-generated: Faker's generic sentence()/paragraph()
output reads as lorem-ipsum-shaped filler, not music-app content -- these
pools are written to sound like real Cuemix listeners talking about music,
so combined with build.py's seeded RNG they read as varied, plausible posts/
bios/messages rather than obviously templated placeholder text. Every pool
is deliberately larger than the number of users/posts that draw from it, and
build.py's picks are randomized (not cycled in order), so no fixed-size
dataset shows an obvious repeat-every-N pattern.

Every fictional artist/track name here is invented for this seed -- none of
them refer to real people, bands, or releases.
"""

FIRST_NAMES = [
    "Maya", "Jordan", "Lucas", "Amara", "Kenji", "Sofia", "Elena", "Marcus",
    "Priya", "Diego", "Zoe", "Noah", "Layla", "Theo", "Amina", "Felix",
    "Nadia", "Owen", "Isabela", "Kwame", "Ingrid", "Rafael", "Chloe", "Amir",
    "Freya", "Malik", "Camille", "Hassan", "Ines", "Leon", "Yara", "Dimitri",
    "Aisha", "Mateo", "Talia", "Kofi", "Selin", "Gabriel", "Naomi", "Anders",
    "Ivy", "Tariq", "Bianca", "Sven", "Rosa", "Idris", "Winona", "Pablo",
    "Meera", "Callum", "Zara", "Julian", "Anya", "Emeka", "Lucia", "Sami",
    "Wren", "Nikolai", "Fatima", "Reid", "Simone",
]

LAST_NAMES = [
    "Reyes", "Whitfield", "Nakamura", "Okoro", "Delacroix", "Bergström",
    "Alvarado", "Mercer", "Osei", "Castellano", "Voss", "Adeyemi",
    "Marchetti", "Kowalski", "Rahman", "Doyle", "Novak", "Fontaine",
    "Ibarra", "Larsen", "Whitmore", "Sato", "Odom", "Guerrero",
    "Lindqvist", "Abara", "Vasiliou", "Bianchi", "Correia", "Halvorsen",
    "Ekwueme", "Salcedo", "Brennan", "Tanaka", "Okafor", "Moreau",
    "Solheim", "Vargas", "Chukwu", "Andresen", "Petrova", "Lindberg",
    "Amadi", "Serrano", "Kallas", "Dubois", "Nwosu", "Haddad",
    "Falk", "Onyekachi", "Rios", "Sundberg",
]

# {vibe} phrases used across bios, session prompts, and post copy -- kept
# lowercase since every template controls its own sentence-start casing.
VIBE_PHRASES = [
    "late night coding", "sunday morning coffee", "gym momentum",
    "deep focus flow", "rainy afternoon calm", "long drive energy",
    "pre-show warmup", "study session hush", "golden hour wind-down",
    "post-workout cooldown", "kitchen dance party", "commute reset",
    "midnight wind-down", "beach sunset drift", "city walk pulse",
    "bedroom production session", "airport layover haze", "campfire glow",
    "first-snow stillness", "rooftop golden hour",
]

GENRES = [
    "Lo-fi Hip-Hop", "Deep House", "Indie Pop", "Synthwave", "Afrobeats",
    "Neo-Soul", "Drum & Bass", "Melodic Techno", "Ambient", "Jazz Fusion",
    "Latin Pop", "K-Pop", "Reggaeton", "Trap", "Alternative Rock",
    "Dream Pop", "Progressive House", "Bedroom Pop", "Funk", "Disco",
    "Chillwave", "Hyperpop", "Acoustic Folk", "UK Garage",
]

# Fictional-only artist names, grouped loosely by the genre they "fit" --
# used for listening events, mix segments, and post/comment copy. None of
# these refer to real people, bands, or releases.
ARTISTS_BY_GENRE = {
    "Lo-fi Hip-Hop": ["Rainy Loft", "Static Bloom", "Paper Tape Club", "Ninth Floor Hum"],
    "Deep House": ["Glass Horizon", "Underlit", "Nightshade Radio", "Low Tide Collective"],
    "Indie Pop": ["Tin Balloon", "Wildflower Static", "The Corner Lamps", "Marigold Radio"],
    "Synthwave": ["Neon Fathom", "Chrome Parallel", "Vector Dusk", "Midnight Freeway"],
    "Afrobeats": ["Lagos Current", "Sundial Rhythm", "Kente Wave", "Golden Harmattan"],
    "Neo-Soul": ["Velvet Static", "Amber Room", "Slow Ember", "Honeytone"],
    "Drum & Bass": ["Fractal North", "Subwoof Theory", "Kinetic Static", "Basement Signal"],
    "Melodic Techno": ["Echo Valley", "Polar Circuit", "Obsidian Loop", "Faultline Radio"],
    "Ambient": ["Quiet Atlas", "Driftglass", "Pale Static", "Long Exposure"],
    "Jazz Fusion": ["Blue Circuit Quartet", "Copperline Trio", "Modal Weather", "Loose Change Ensemble"],
    "Latin Pop": ["Costa Dorada", "Ritmo Bajo", "Sal y Luz", "Nocturno Habana"],
    "K-Pop": ["Prism Six", "Neon Orchid", "Halo Static", "Seoul Radio Club"],
    "Reggaeton": ["Calle Sur", "Bajo Perreo", "Isla Nocturna", "Ritmo Caribe"],
    "Trap": ["808 Parish", "Concrete Bloom", "Dusk Cartel", "Low End Chapel"],
    "Alternative Rock": ["Hollow Static", "Rust Parade", "Kerosene Choir", "Broken Antenna"],
    "Dream Pop": ["Pale Radio", "Soft Static", "Glasswing", "Cathedral Haze"],
    "Progressive House": ["Long Arc", "Skyline Theory", "Ninth Wave", "Solar Drift"],
    "Bedroom Pop": ["Sunday Static", "Cardboard Moon", "Slow Bloom", "Attic Radio"],
    "Funk": ["Brass Static", "Groove Parish", "Copper Pocket", "Uptown Circuit"],
    "Disco": ["Mirrorball Static", "Satin Groove", "Studio Nine", "Velvet Circuit"],
    "Chillwave": ["Faded Postcard", "Pastel Static", "Slow Tide", "Sun-Bleached Radio"],
    "Hyperpop": ["Glitch Bloom", "Pixel Static", "Neon Crash", "Overdrive Petal"],
    "Acoustic Folk": ["Wren & Timber", "Copper Meadow", "Quiet Pines", "Riverbend Radio"],
    "UK Garage": ["Two-Step Static", "Bassline Parish", "Pirate Freq", "Late Tube Radio"],
}

MOODS = [
    "chill", "energetic", "focused", "romantic", "melancholic", "upbeat",
    "dreamy", "intense", "nostalgic", "groovy", "wistful", "triumphant",
]

BIO_TEMPLATES = [
    "{genre1} on repeat, {genre2} when I need a change of pace.",
    "Building the perfect {vibe} playlist, one mix at a time.",
    "{genre1} head. Also secretly love {genre2}.",
    "DJ-curious. Mostly here for {genre1} and {genre2} discoveries.",
    "Collecting {vibe} mixes like other people collect vinyl.",
    "{genre1} on the way in, {genre2} on the way out.",
    "Trying to convert everyone I know to {genre1}.",
    "Here for the {vibe} mixes and the arguments about {genre1}.",
    "Weekend DJ, weekday {genre1} enjoyer.",
    "{genre1} evangelist. Send me your best {genre2} tracks.",
    "Making {vibe} mixes so I don't have to make small talk.",
    "Grew up on {genre1}, still not over {genre2}.",
    "Music nerd. Mostly {genre1}, occasionally {genre2}.",
    "Looking for my next {genre1} obsession.",
    "{vibe} is basically a personality trait at this point.",
    "Curating {genre1} mixes for anyone who'll listen.",
    "Half my library is {genre1}, the other half is unexplainable.",
    "New to {genre2}, obsessed already.",
    "{genre1} lifer. {genre2} convert.",
    "Chasing the perfect {vibe} transition since forever.",
    None,  # some bios stay unset -- not every real profile fills this in.
    None,
]

DISCUSSION_TOPICS = [
    (
        "What's the most underrated {genre} track you've heard lately?",
        "I keep going back to a track I found last week and I can't believe "
        "it doesn't have more plays. What's on your underrated {genre} list "
        "right now?",
    ),
    (
        "Best transition style for {genre} into {genre2}?",
        "I've been trying to bridge {genre} into {genre2} in my sets and it "
        "always feels a little abrupt. Anyone have a transition trick that "
        "actually works for this?",
    ),
    (
        "{genre} recommendations for a {vibe} session?",
        "Building a playlist for {vibe} and I want it to lean {genre}. Drop "
        "your favorites, I'll take anything.",
    ),
    (
        "Is {genre} having a moment again or is it just my feed?",
        "Feels like every other track my friends send me lately is {genre}. "
        "Is this an actual trend or am I just deep in an algorithm loop?",
    ),
    (
        "How do you discover new {genre} artists?",
        "My usual sources have gone quiet lately. Where is everyone finding "
        "fresh {genre} right now?",
    ),
    (
        "{genre} vs {genre2}: which one wins your {vibe} playlist?",
        "Genuinely torn between the two for my {vibe} rotation this month. "
        "Curious which one wins in your queue and why.",
    ),
    (
        "Anyone else getting really into {genre} lately?",
        "Wasn't expecting to fall this hard for {genre} this year but here "
        "we are. What pulled you into it, if you're also in deep?",
    ),
    (
        "Favorite {genre} track to open a set with?",
        "Looking for a strong opener that leans {genre} without front-loading "
        "too much energy. What's working for you?",
    ),
    (
        "Does anyone else's {vibe} playlist just turn into all {genre} eventually?",
        "Every time I build one of these it drifts toward {genre} by track "
        "ten. Is that just me?",
    ),
    (
        "What made you fall in love with {genre}?",
        "Trying to figure out my own answer to this and coming up blank. "
        "What was the track or moment that did it for you?",
    ),
]

STATUS_BODIES = [
    "Three hours into a {vibe} session and I'm not stopping anytime soon.",
    "{genre} has completely taken over my queue this week.",
    "Found a new {genre} track and I've had it on loop since this morning.",
    "Mixing {genre} into my {vibe} playlist and it's working better than expected.",
    "This {vibe} mix might be my best one yet, not going to lie.",
    "Currently deep in a {genre} rabbit hole, send help (or more tracks).",
    "Nothing beats a good {vibe} session on a day like today.",
    "Just discovered a {genre} artist that's about to ruin my productivity.",
    "{vibe} + {genre} is an underrated combo, more people should try it.",
    "Rebuilt my {vibe} playlist from scratch and it was worth every minute.",
    "That feeling when a {genre} transition lands exactly right.",
    "Somehow ended up on a {genre} kick again. No regrets.",
    "This is your sign to make a {vibe} playlist this weekend.",
    "Can't stop listening to {genre} today, it's just hitting different.",
    "Started with {genre}, ended up somewhere completely different. Love when that happens.",
]

MIX_SHARE_CAPTIONS = [
    "Made this for {vibe} sessions, hope it hits the same for you.",
    "My current go-to {genre} rotation, sharing in case anyone needs it.",
    "This one took a while to get right but I'm happy with the flow.",
    "A little {genre} mix for anyone who needs {vibe} energy today.",
    "Built this after a long {vibe} weekend, figured I'd share.",
    "Not the most polished set but the {genre} picks are solid.",
    "Made for a friend's {vibe} playlist request, sharing here too.",
    "This mix leans hard into {genre}, fair warning.",
    "Been sitting on this one for a week, finally ready to share.",
    "A {vibe} mix that turned into mostly {genre} by the end. No complaints.",
]

COMMENT_BODIES = [
    "This is exactly what I needed today, thank you.",
    "Adding this to my queue immediately.",
    "Completely agree, this has been on repeat for me too.",
    "Underrated take, more people need to hear this.",
    "I felt this in my chest, honestly.",
    "Sending this to my group chat right now.",
    "This is such a good pick, well done.",
    "Been thinking about this exact thing lately.",
    "Solid choice, I'd add one more to that list though.",
    "This mix is criminally underrated.",
    "Same energy over here, glad it's not just me.",
    "Perfect timing, needed this for my playlist.",
    "This take is correct and you should feel correct.",
    "Can confirm, this genuinely slaps.",
    "The transition at the end got me, so smooth.",
    "This is going straight into my saved list.",
    "Honestly didn't expect this combo to work but it does.",
    "Great question, following for the replies.",
    "This is the kind of post I come here for.",
    "Been looking for something like this all week.",
]

DM_OPENERS = [
    "hey, have you heard the new stuff from {artist}?",
    "ok this is random but you'd love this {genre} mix I found",
    "quick question, what's that track you played last time we hung out?",
    "sending you this before I forget, it's very {vibe}",
    "you around this weekend? want to build a playlist together",
    "just found your kind of {genre}, sending immediately",
    "ok I need your opinion on this mix I made",
    "have you tried mixing {genre} into your sets? works better than I thought",
]

DM_REPLIES = [
    "yes!! been listening to it nonstop",
    "omg yes send it over",
    "I think it was {artist}, let me check",
    "that's so on brand for you honestly",
    "I'm free saturday, let's do it",
    "already added to my queue, thank you",
    "sending you mine too then",
    "okay this might be my new favorite",
    "haha fair, I'll give it a real listen tonight",
    "wait this is actually really good",
]

SESSION_PROMPT_TEMPLATES = [
    "Create a {vibe} mix with {mood} energy and smooth transitions.",
    "Build a {genre}-leaning set for {vibe}, keep it {mood}.",
    "I want a {mood} {vibe} mix, mostly {genre}.",
    "Put together a {vibe} playlist that stays {mood} throughout.",
    "Make me a {genre} mix for {vibe}, {mood} but not overwhelming.",
    "{vibe} session, {mood} mood, lean into {genre}.",
    "Something {mood} for {vibe}, open to {genre} picks.",
]

# Combined pairwise (adjective + noun) by build.py to generate a large pool
# of plausible-sounding fictional track titles without hand-listing hundreds.
TRACK_TITLE_ADJECTIVES = [
    "Neon", "Hollow", "Velvet", "Slow", "Static", "Golden", "Pale", "Low",
    "Quiet", "Electric", "Faded", "Amber", "Night", "Loose", "Bright",
]
TRACK_TITLE_NOUNS = [
    "Drift", "Pulse", "Bloom", "Horizon", "Static", "Signal", "Tide",
    "Echo", "Freeway", "Parallel", "Circuit", "Glow", "Radio", "Reprise",
    "Motion",
]

FEEDBACK_PHRASES = {
    "more_energy": ["more energy please", "can we pick up the pace", "need more energy here"],
    "less_vocals": ["less vocals please", "too many vocals, tone it down", "give me less vocals"],
    "smoother": ["smoother transitions please", "make this smoother", "smoother please"],
    "reinforce": ["this is great, more like this", "love this one", "exactly what I wanted"],
}
