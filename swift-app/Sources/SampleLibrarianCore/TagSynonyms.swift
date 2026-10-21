import Foundation

/// Search-time alias resolution so typing a synonym of a real tag (e.g. "drum
/// and bass", "DrumNBass", "jungle" for the `dnb` tag) resolves to that tag's
/// chip instead of becoming inert free text. Mirrors config/taxonomy.yaml's
/// keyword lists (the classification-time source of truth) -- MUST be kept
/// in sync by hand when that file changes, same convention as
/// `SearchQueryParser.parseKey` mirroring `filename_regex.py`.
///
/// Only keyword variants that *differ* from an actual tag name are listed
/// here -- a word that's already a real tag (e.g. "kick", "melodic") is
/// caught by `SearchQueryParser.recognizeToken`'s `knownTags` check before
/// this table is ever consulted, so entries here are safe even if they
/// happen to overlap with a live tag name.
enum TagSynonyms {
    /// Multi-word alias phrases, keyed by the phrase already lowercased with
    /// its words joined by a single space (matching how
    /// `SearchQueryParser.commitTokens` normalizes consecutive words before
    /// looking a phrase up) -> the canonical tag name.
    static let phraseSynonyms: [String: String] = [
        "drum and bass": "dnb",
        "drum n bass": "dnb",
        "kick drum": "kick",
        "rim shot": "rimshot",
        "rim click": "rimshot",
        "hi hat": "hihat",
        "vocal chop": "vocalchop",
        "vox chop": "vocalchop",
        "ad lib": "adlib",
        "vocal tag": "adlib",
        "full kit": "drumkit",
        "drum kit": "drumkit",
        "beat loop": "drumkit",
        "drum loop": "breakbeat",
        "bass line": "bass",
        "sub bass": "sub",
        "electric guitar": "guitar",
        "acoustic guitar": "guitar",
        "guitar riff": "guitar",
        "grand piano": "piano",
        "upright piano": "piano",
        "build up": "drumfill",
        "uk garage": "garage",
        "lo fi": "lofi",
        "hip hop": "hiphop",
        "r n b": "rnb",
        "rhythm and blues": "rnb",
        "electronic dance": "edm",
        "uk drill": "drill",
        "chip tune": "chiptune",
        "world music": "world",
        "chill out": "downtempo",
        "hyper pop": "hyperpop",
        "one shot": "one-shot",
        "wood block": "woodblock",
        "field recording": "ambience",
    ]

    /// Single-word (or dash-joined single-token, e.g. "8-bit") aliases,
    /// lowercased -> canonical tag name.
    static let wordSynonyms: [String: String] = [
        // Drums / percussion
        "bd": "kick",
        "bassdrum": "kick",
        "sd": "snare",
        "hh": "hihat",
        "drumloop": "breakbeat",
        "break": "breakbeat",
        "groove": "breakbeat",
        "bassline": "bass",
        "subbass": "sub",
        "eight-oh-eight": "808",
        "wood-block": "woodblock",
        // Melodic / harmonic
        "gtr": "guitar",
        "strum": "guitar",
        "strumming": "guitar",
        "violin": "strings",
        "cello": "strings",
        "viola": "strings",
        "orchestra": "strings",
        "orchestral": "strings",
        "horn": "brass",
        "trumpet": "brass",
        "sax": "brass",
        "saxophone": "brass",
        "trombone": "brass",
        "flute": "woodwind",
        "clarinet": "woodwind",
        "oboe": "woodwind",
        "bassoon": "woodwind",
        "arpeggio": "arp",
        "arpeggiated": "arp",
        // Vocal
        "vox": "vocal",
        "acappella": "acapella",
        "choral": "choir",
        "shout": "adlib",
        // FX / texture
        "sfx": "fx",
        "uplifter": "riser",
        "downlifter": "sweep",
        "whoosh": "transition",
        "field": "ambience",
        "static": "noise",
        "hiss": "noise",
        "crackle": "noise",
        "vinyl": "noise",
        "stutter": "glitch",
        "error": "glitch",
        // Genre / style
        "ukg": "garage",
        "jungle": "dnb",
        "drumnbass": "dnb",
        "rap": "hiphop",
        "trailer": "cinematic",
        "epic": "cinematic",
        "reggaeton": "latin",
        "r&b": "rnb",
        "randb": "rnb",
        "electro": "edm",
        "retrowave": "synthwave",
        "outrun": "synthwave",
        "8bit": "chiptune",
        "8-bit": "chiptune",
        "chillout": "downtempo",
        "chill": "downtempo",
        // Loop / one-shot (dynamically-derived tags, not taxonomy keywords,
        // but "one-shot" is spelled with a dash as the real tag -- these
        // catch the no-dash/abbreviated ways someone would type it)
        "oneshot": "one-shot",
        "1shot": "one-shot",
        "1shots": "one-shot",
    ]
}
