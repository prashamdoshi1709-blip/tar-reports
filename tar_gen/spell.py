"""Spelling support with hunspell (en_AU + en_US dictionaries; free, local, no network).

  known(words)          which lower-case words are ordinary dictionary words (used to restore case in Vitti's
                        upper-case labels: ordinary words lower-cased, acronyms such as CLS or HPC kept)
  typos(text)           likely typing errors: a lower-case word the dictionaries do not know AND for which hunspell
                        suggests a word one edit away ("recieve" -> "receive"). Unknown words without a near
                        suggestion are treated as names or jargon, not errors, so legitimate terms do not stop a report.

If hunspell is missing, known() falls back to a small built-in list and typos() raises SpellUnavailable: the
pipeline then refuses to publish (fail closed). The workflows install hunspell.
"""
import functools, re, shutil, subprocess

ALLOW = {"capex", "opex", "counterparty", "unfranked", "unfinalised", "pcp", "pharma", "breakeven", "forma", "wks", "buyback",
         "buybacks", "adj", "cc", "cps", "eps", "npat", "ebitda", "ebit", "offtake", "offtakes", "tolling", "earnout", "guidance",
         "midpoint", "dividend", "franked", "headroom", "pre", "ytd", "yoy", "hoh", "qoq", "bps", "approx", "vs", "etc", "mpc"}
FALLBACK_COMMON = set("""a an the of in on to for and or per net new sale cash debt up as at by from total share move last first
fell rose rises falls jumps two three four five years year of after below above over under its it is are was were be been with
without into out than that this these those via now not no yes back down guidance revenue sales growth margin profit loss deal
offer price value target targeted expected expects completion consideration contract order book backlog cancellation recovery
implementation underlying adjusted reported group limited trading update result results half full quarter
buy sell off end low high key top mid pay set all any one per its""".split())


class SpellUnavailable(Exception):
    pass


def _hunspell():
    return shutil.which("hunspell")


@functools.lru_cache(maxsize=4096)
def _check(word):
    """('ok'|'miss'|'near', suggestions) for one word."""
    out = subprocess.run(["hunspell", "-a", "-d", "en_AU,en_US"], input="^" + word + "\n", capture_output=True, text=True).stdout
    for line in out.splitlines()[1:]:
        if line.startswith(("*", "+", "-")):
            return "ok", ()
        if line.startswith("&"):
            sugg = tuple(s.strip() for s in line.split(":", 1)[1].split(","))
            return "near", sugg
        if line.startswith("#"):
            return "miss", ()
    return "ok", ()


def known(word):
    w = word.lower()
    if not _hunspell():
        return w in FALLBACK_COMMON
    return _check(w)[0] == "ok"


def _osa(a, b):
    """Optimal string alignment distance (Damerau-Levenshtein with adjacent transpositions)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            c = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def typos(text):
    if not _hunspell():
        raise SpellUnavailable("hunspell is not installed")
    found = []
    for tok in re.findall(r"[A-Za-z][A-Za-z'’\-]*", text):
        for part in tok.split("-"):
            w = part.strip("'’")
            if len(w) < 3 or not w.islower() or w in ALLOW or w.endswith(("'s", "’s")):
                continue
            status, sugg = _check(w)
            if status == "near" and any(_osa(w, s.lower()) <= 1 for s in sugg if " " not in s and "-" not in s):
                found.append(w)
    return sorted(set(found))
