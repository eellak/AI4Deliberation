"""Prompt templates & retry-handling utilities.
Focuses on Stage 1–3 without 2.4–2.6 re-join logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

# ===========================================================================
# ACTIVELY USED PROMPTS - Stage 1 (Article Summarization)
# Used in: workflow.py for summarizing individual articles
# ===========================================================================

STAGE1_PROMPT = (
    "Παρακαλώ δημιουργήστε μια σύντομη περίληψη του παρακάτω κειμένου στα Ελληνικά, σε απλή γλώσσα, "
    "κατάλληλη για πολίτες χωρίς εξειδικευμένες νομικές γνώσεις. Η περίληψη πρέπει να είναι έως {target_sentences} προτάσεις "
    "και περίπου {target_words} λέξεις (όριο {token_limit} tokens).\n"
    "Προσοχή να μη παραλειφθούν αλλαγές σε νόμους, θεσμούς, ή διαδικασίες αν πρόκειται για νομοθετικό άρθρο.\n"
    "Οι περιλήψεις πρέπει να είναι όσο πιο σύντομες γίνεται, διατηρώντας την ουσία του κειμένου και να μην υπερβαίνουν τις {target_sentences} προτάσεις.\n"
    "Σκοπός είναι η κατανόηση του περιεχομένου σε μια πλατφόρμα ηλεκτρονικής διαβούλευσης – μην προσθέτετε εισαγωγική φράση, απλώς γράψτε την περίληψη:"
)

# ===========================================================================
# ACTIVELY USED PROMPTS - Stage 2 (Chapter Summarization)
# Used in: stage23_helpers.py and stage23_helpers_v2.py
# ===========================================================================

STAGE2_CHAPTER_PROMPT = (
    "[SCHEMA:CHAPTER_SUM] \n"
    "Οι παρακάτω λίστα περιέχει σύντομες περιλήψεις άρθρων του ίδιου ΚΕΦΑΛΑΙΟΥ. Κάθε άρθρο είτε τροποποιεί/καταργεί υπάρχουσες διατάξεις είτε εισάγει νέες. "
    "Συνδύασέ τες σε μία συνεκτική περίληψη στα Ελληνικά, με απλή γλώσσα (ιδανικά με μήκος ~{target_words} λέξεις), εστιάζοντας ξεκάθαρα στο ΤΙ αλλάζει ή εισάγει το νομοσχέδιο και πώς επηρεάζει τους πολίτες. "

    "Επέστρεψε **ΜΟΝΟ** έγκυρο JSON με το ακόλουθο σχήμα και καμία επιπλέον λέξη:\n"
    "{{\n  \"summary\": \"...\"\n}}"
)

# ===========================================================================
# ACTIVELY USED PROMPTS - Stage 3 (Part Summarization)
# ===========================================================================

# Legacy single-stage part summarization (still in use as fallback)
# Used in: stage23_helpers.py and stage23_helpers_v2.py
STAGE3_PART_PROMPT = (
    "[SCHEMA:PART_SUM] \n"
    "Οι παρακάτω σύντομες περιλήψεις αντιστοιχούν στα ΚΕΦΑΛΑΙΑ ενός ΜΕΡΟΥΣ του νομοσχεδίου προς ψήφιση. "
    "Συμπύκνωσέ τες σε μία πλήρη περίληψη (ιδανικά με μήκος ~{target_words} λέξεις) "
    "που περιγράφει τον συνολικό σκοπό του Μέρους, σε απλή γλώσσα.\n"
    "Μην αναφέρεσαι σε συγκεκριμένα άρθρα ή παραγράφους των νόμων που μπορεί να αλλάζουν.\n"
    "Η περίληψη σου αυτή είναι για ένα Μέρος του νομοσχεδίου όχι για όλο το νομοσχέδιο.\n"
    "Μην αναφέρεσαι σε όλο το νομοσχέδιο εκτός και αν χρειάζεται ειδική αναφορά μέσα στο κείμενο.\n"
    "Δημιούργησε μια αφηγηματική περίληψη των αλλαγών που εφαρμόζει ο νόμος από το πρώτο κεφάλαιο μέχρι το τελευταίο\n"
    "ώστε ένας απλός πολίτης να μπορεί να καταλάβει που στοχεύει ο νόμος και τι αλλαγές επιφέρει.\n"
    "Ξεκίνα την απάντηση σου με 'Ο σκοπός του μέρους είναι'.\n"
    "Επέστρεψε **ΜΟΝΟ** το εξής JSON χωρίς καμία άλλη λέξη:\n"
    "{{\n  \"summary\": \"...\"\n}}"
)

# Prefixes for part Σκοπός/Αντικείμενο (if provided)
# Used in: stage23_helpers.py
STAGE3_PART_SKOPOS_PREFIX = (
    "Ο σκοπός του Μέρους όπως περιγράφεται από το υπουργείο είναι: "
)

STAGE3_PART_ANTIKEIMENO_PREFIX = (
    "Το αντικείμενο του Μέρους όπως περιγράφεται από το υπουργείο είναι: "
)

# ===========================================================================
# ACTIVELY USED PROMPTS - Stage 3 Expansion (Two-Stage Narrative Workflow)
# Used in: stage3_expanded.py
# ===========================================================================

# Dynamic narrative plan prompt with variable beat count placeholders (PRIMARY)
STAGE3_PLAN_DYN_PROMPT = """[SCHEMA:NARRATIVE_PLAN]\n**Ρόλος (Persona):**
Είστε ένας διακεκριμένος δημοσιογράφος, με πολυετή εμπειρία στην κάλυψη υπο διαβούλευση νομοσχεδίων.
Στόχος σας είναι να μεταφράζετε πολύπλοκες νομοθετικές αλλαγές σε απλή, κατανοητή και συνεκτική γλώσσα.

**Οδηγίες:**
Σας παρέχονται (προαιρετικά) τα κείμενα «Σκοπός» / «Αντικείμενο» και οι περιλήψεις των κεφαλαίων ενός Μέρους.
Δημιουργήστε αφηγηματικό σχέδιο με **{min_beats}–{max_beats}** θεματικές ενότητες.

Επιστρέφεις ΜΟΝΟ έγκυρο JSON, κανέναν άλλον χαρακτήρα πριν ή μετά:
{{
  "overall_narrative_arc": "Μία πρόταση που συνοψίζει το συνολικό αφήγημα",
  "protagonist": "Ποιος επηρεάζεται κυρίως (πολίτες, επιχειρήσεις κ.λπ.)",
  "problem": "Το βασικό πρόβλημα που επιλύεται",
  "narrative_sections": [
    {{
      "section_title": "Περιεκτικός τίτλος",
      "section_role": "Πώς συμβάλλει στη συνολική αφήγηση",
      "source_chapters": ["kefalaio_0", "kefalaio_1"]
    }}
  ]
}}

ΟΔΗΓΙΕΣ:
- narrative_sections: λίστα **{min_beats}–{max_beats}** ενοτήτων.
- section_title: ≤10 λέξεις.
- source_chapters: ΧΡΗΣΙΜΟΠΟΙΗΣΕ **ακριβώς** τις αναφορές που σου δίνονται (π.χ. "kefalaio_0").
- Επιτρεπτά κεφάλαια: {allowed_keys_csv}
- Εύρος αριθμών κεφαλαίων: {allowed_range}
- Επέλεξε κεφάλαια μόνο μέσα στο εύρος αριθμών κεφαλαίων που είδες παραπάνω. Αριθμοί έξω από αυτό το εύρος είναι άκυροι και θα οδηγήσουν σε κυρώσεις.

**Δεδομένα Εισόδου:**
{input_data_json}

ΘΥΜΉΣΟΥ: Επιστρέφεις ΜΟΝΟ έγκυρο JSON."""

# Fast-track prompt for single-chapter Parts
STAGE3_SINGLE_CHAPTER_PROMPT = """[SCHEMA:SINGLE_CHAPTER_SUMMARY]\n**Ρόλος (Persona):**\nΕίστε έμπειρος δημοσιογράφος ειδικευμένος στην ανάλυση νομοθεσίας.\n\nΣυνοψίστε το ακόλουθο Κεφάλαιο σε **120-150** λέξεις,\nμε απλή γλώσσα και έμφαση στον τρόπο που επηρεάζει τους πολίτες.\n\nΕπιστρέφεις ΜΟΝΟ έγκυρο JSON, κανέναν άλλον χαρακτήρα πριν ή μετά:\n{{\n  "summary": "Η συνοπτική παράγραφος ..."\n}}\n\nΟΔΗΓΙΕΣ:\n- summary: μία παράγραφος, 120-150 λέξεις, κατανοητή, χωρίς νομικίστικη φρασεολογία.\n- Ξεκίνα με σύντομη αναφορά στο θέμα του Κεφαλαίου.\n\nΘΥΜΉΣΟΥ: Επιστρέφεις ΜΟΝΟ έγκυρο JSON."""

# Chunk synthesis prompt for narrative sections
STAGE3_SYNTH_PROMPT = """[SCHEMA:NARRATIVE_SECTION]\n**Ρόλος (Persona):**
Είστε ένας διακεκριμένος δημοσιογράφος, με πολυετή εμπειρία στην κάλυψη νομοθετικού έργου για μεγάλα ειδησεογραφικά μέσα. Το πάθος σας είναι η προάσπιση της δημοκρατίας μέσω της έγκυρης ενημέρωσης. Στόχος σας είναι να "μεταφράζετε" πολύπλοκες νομοθετικές αλλαγές σε απλή, κατανοητή και συνεκτική γλώσσα για το ευρύ κοινό.

**Οδηγίες:**
Σας παρέχω ολόκληρο το αφηγηματικό σχέδιο για ένα Μέρος της νομοθεσίας, τις αρχικές περιλήψεις των κεφαλαίων που σχετίζονται με **μία συγκεκριμένη ενότητα**, και τον τίτλο της ενότητας που πρέπει να συγγράψετε.

1. **Κατανοήστε το Πλαίσιο:** Μελετήστε το αφηγηματικό σχέδιο για να αντιληφθείτε πώς η συγκεκριμένη ενότητα εντάσσεται στη συνολική αφήγηση.
2. **Συγγράψτε την Ενότητα:** Δημιουργήστε μία συνεκτική και πληροφοριακή παράγραφο που συνοψίζει το περιεχόμενο των σχετικών κεφαλαίων.
3. **Συμπίεση & Ποιότητα:** Η παράγραφος πρέπει να είναι περιεκτική (~60-80 λέξεις), με απλή γλώσσα, αποφεύγοντας νομικούς όρους όπου είναι δυνατόν.

Επιστρέφετε **μόνο** έγκυρο JSON, κανέναν άλλον χαρακτήρα πριν ή μετά:

{
  "current_section_text": "Η παράγραφος που συνοψίζει αυτή την ενότητα του νομοθετικού μέρους..."
}

ΟΔΗΓΙΕΣ:
- current_section_text: Περιεκτική παράγραφος 60-80 λέξεων που συνοψίζει την ενότητα
- Χρησιμοποιήστε απλή, κατανοητή γλώσσα
- Ξεκινήστε με εισαγωγική αναφορά στον τίτλο της ενότητας
- Εστιάστε στο πώς επηρεάζει τους πολίτες

ΘΥΜΉΣΟΥ: Επιστρέφεις ΜΟΝΟ έγκυρο JSON."""

# ===========================================================================
# ACTIVELY USED PROMPTS - Polishing Stage (Post-Narrative)
# Used in: generate_stage2_3_summaries.py
# ===========================================================================

# Stylistic critique prompt (step 1 of polishing)
CITIZEN_POLISH_PROMPT = (
    "[SCHEMA:CITIZEN_POLISH_SUMMARY]\n"
    "Είσαι ένας έμπειρος συντάκτης που αναλαμβάνει να εξηγήσει το «{part_name}» ενός πολύπλοκου νομοσχεδίου στο ευρύ κοινό.\n\n"
    "Η απάντησή σου πρέπει να είναι **ένα και μόνο ένα έγκυρο αντικείμενο JSON** και τίποτα άλλο.\n\n"
    "Το αντικείμενο JSON πρέπει να έχει την εξής δομή:\n"
    "{\n  \"explanation\": \"Μια σύντομη εξήγηση της στρατηγικής που θα ακολουθήσεις.\",\n  \"plan\": \"Ένα σχέδιο σε βήματα για το πώς θα συνθέσεις το κείμενο.\",\n  \"summary_text\": \"Το τελικό, ευανάγνωστο κείμενο της περίληψης.\"\n}\n\n"
    "Οδηγίες για το περιεχόμενο του κάθε πεδίου:\n"
    "1.  **explanation**: Εξήγησε σύντομα τη στρατηγική σου. Τόνισε ότι ο στόχος είναι η σαφήνεια για το ευρύ κοινό και όχι η νομική ακρίβεια.\n"
    "2.  **plan**: Περιέγραψε τα βήματα που θα ακολουθήσεις, όπως η ομαδοποίηση ανά θέμα, η αφαίρεση επαναλήψεων και η απλοποίηση της γλώσσας.\n"
    "3.  **summary_text**: Γράψε το τελικό, ενιαίο κείμενο. Επικεντρώσου στο να είναι ευανάγνωστο, ομαδοποιώντας τις ιδέες λογικά και αποφεύγοντας τους αριθμούς άρθρων και την περιττή νομική ορολογία. Χρησιμοποίησε το «{part_name}» ως υποκείμενο.\n\n"
    "Οι παράγραφοι προς επεξεργασία είναι οι εξής:\n"
)

STAGE3_CRITIQUE_PROMPT = (
    "[SCHEMA:STYLISTIC_CRITIQUE] \n"
    "Είσαι επιμελητής ύφους. Θα λάβεις ένα δημοσιογραφικό κείμενο που συνοψίζει μέρος νομοσχεδίου.\n"
    "Εντόπισε έως 15 σύντομες φράσεις ή σημεία που πάσχουν από:\n"
    "- Κακή γραμματική, ή δυσνόητη σύνταξη\n"
    "- Επαναλήψεις λέξεων ή φράσεων, π.χ. αν κάθε παράγραφος ξεκινά με τις ίδες λέξεις\n"
    "- Ασαφείς ή δυσνόητες εκφράσεις\n"
    "Για καθεμία, δώσε:\n"
    "1. original_phrase – σύντομο απόσπασμα έως 120 χαρακτήρες\n"
    "2. issue – πολύ σύντομη περιγραφή (π.χ. 'περίπλοκη σύνταξη')\n"
    "3. suggestion – λίστα 1-2 εναλλακτικών, πιο απλών διατυπώσεων\n"
    "Επιστρέφεις **ΜΟΝΟ** έγκυρο JSON χωρίς καμία άλλη λέξη.\n"
    "INPUT:\n"
)

JOURNALISTIC_POLISH_PROMPT = (
    "[SCHEMA:POLISHED_SUMMARY] \n"
    "Το παρακάτω είναι περίληψη ενός μέρος νομοσχεδίου. Είσαι ειδικός συντάκτης που διορθώνει λάθη στη γραμματική, στην έκφραση και την ορθογραφία.\n"
    "Διόρθωσε επαναλήψεις και βελτίωσε τη σύνταξη χωρίς να μεταβάλεις τα γεγονότα, ονόματα, ή σχέσεις που υπάρχουν μέσα στο κέιμενο.\n"
    "Βελτίωσε μόνο τη γραμματική, την ορθογραφία και την έκφραση χωρίς να αλλάξεις την μορφοποίηση (formatting), ουσία ή το νόημα του κειμένο. Αν το κείμενο έχει πολλές παραγράφους διατήρησε αυτή τη μορφή.\n"
    "Παραδείγματα αλλαγών που μπορείς να κάνεις:\n\n"
    "Αν υπάρχει η κακή γραμματική: 'Ο σκοπός του μέρους είναι το νομοσχέδιο στοχεύει' απλοποίησε το σε 'Το μέρος στοχεύει',\n"
    "Αν υπάρχει επανάληψη ρήματος/ουσιαστικού (π.χ. ενίσχυση/ενισχύσεων) όπως: 'ενίσχυση των κρατικών ενισχύσεων για μικρομεσαίες επιχειρήσεις' απλοποίησε το σε 'ενίσχυση των μικρομεσαίων επιχειρήσεων'"
    "Επιστρέφεις **ΜΟΝΟ** έγκυρο JSON χωρίς καμία άλλη λέξη:\n"
    "{\n  \"polished_text\": \"...\"\n}\n"
    "στο JSON σου πρέπει να επιστέφεις και αλλαγή σειράς \\n όπου υπάρχει αλλαγή σειράς στο κείμενο\n"
    "INPUT:\n"
)

# ===========================================================================
# ACTIVELY USED PROMPTS - Law Classification (Modifications & New Provisions)
# Used in: workflow.py for classifying law modifications and new provisions
# ===========================================================================

LAW_MOD_JSON_PROMPT_W_MDATA = (
    """Το παρακάτω κείμενο τροποποιεί, καταργεί ή συμπληρώνει προϋπάρχουσες
    διατάξεις νόμου. Επιστρέφεις **μόνο** έγκυρο JSON, κανέναν άλλον
    χαρακτήρα πριν ή μετά:

    {
      "law_reference": "<αριθμός_νόμου>/<έτος>",
      "article_number": "<άρθρο ή παράγραφος που αλλάζει>",
      "change_type": "<τροποποιείται|καταργείται|αντικαθίσταται|προστίθεται|συμπληρώνεται|διαγράφεται>",
      "major_change_summary": "<έως 40 λέξεις που εξηγούν ΤΙ αλλάζει και ΓΙΑΤΙ είναι σημαντικό· αγνόησε αναριθμήσεις ή καθαρά παραπομπές>",
      "key_themes": ["<keyword_1>", "<keyword_2>", "<keyword_3>"]
    }

    ΟΔΗΓΙΕΣ ΓΙΑ major_change_summary
    - Περιέγραψε την ουσία και τον στόχο της αλλαγής (πολιτική, δικαιούχοι, διαδικασία).
    - Μην αναφέρεις κωδικούς ΦΕΚ ή αρίθμηση άρθρων.
    - Πρέπει να είναι 1-2 προτάσεις σε μήκος


    ΟΔΗΓΙΕΣ ΓΙΑ key_themes
    - 1-3 αγγλικές λέξεις η καθεμία, με κάτω παύλα αντί για κενά, χωρίς σημεία στίξης.

    ΠΑΡΑΔΕΙΓΜΑ
    {
      "law_reference": "ν. 1234/2023",
      "article_number": "άρθρο 5",
      "change_type": "τροποποιείται",
      "major_change_summary": "Μετατοπίζει τη στήριξη από αποκλειστικά νεοφυείς επιχειρήσεις σε ευρύτερο καθεστώς ψηφιακού μετασχηματισμού, διευρύνοντας τους δυνητικούς δικαιούχους.",
      "key_themes": ["digital_transformation", "broadening_of_beneficiaries"]
    }

    ΘΥΜΉΣΟΥ: Επιστρέφεις ΜΟΝΟ έγκυρο JSON."""
)

LAW_NEW_JSON_PROMPT = (
    """Το παρακάτω κείμενο εισάγει νέες διατάξεις, ορισμούς ή ρυθμίσεις χωρίς να τροποποιεί προϋπάρχοντες νόμους.
    Επιστρέφεις **μόνο** έγκυρο JSON, κανέναν άλλον χαρακτήρα πριν ή μετά:

    {
      "article_title": "<τίτλος άρθρου>",
      "provision_type": "<ορισμός|αρμοδιότητες|διαδικασία|οργάνωση|ρύθμιση|διάρθρωση|κυρώσεις|οικονομικά>",
      "core_provision_summary": "<έως 40 λέξεις που εξηγούν ΤΙ θεσπίζεται και ΠΟΙΟΝ αφορά>",
      "key_themes": ["<keyword_1>", "<keyword_2>", "<keyword_3>"]
    }

    ΟΔΗΓΙΕΣ ΓΙΑ core_provision_summary
    - Περιέγραψε τι καθιερώνεται/ορίζεται και την πρακτική του σημασία.
    - Εστίασε στην ουσία, όχι σε διαδικαστικές λεπτομέρειες.
    - Πρέπει να είναι 1-2 προτάσεις σε μήκος

    ΟΔΗΓΙΕΣ ΓΙΑ provision_type
    - ορισμός: θεσμική φύση, έννοιες, κατηγορίες
    - αρμοδιότητες: καθήκοντα και εξουσίες φορέων
    - διαδικασία: μέθοδοι και βήματα εφαρμογής
    - οργάνωση: δομές και ιεραρχία
    - ρύθμιση: κανόνες και υποχρεώσεις
    - διάρθρωση: συγκρότηση και σύνθεση οργάνων
    - κυρώσεις: θέσπιση ποινών ή διοικητικών κυρώσεων
    - οικονομικά: καθορισμός προϋπολογισμών, χρηματοδοτήσεων 


    ΟΔΗΓΙΕΣ ΓΙΑ key_themes
    - 1-3 αγγλικές λέξεις η καθεμία, με κάτω παύλα αντί για κενά, χωρίς σημεία στίξης.

    ΠΑΡΑΔΕΙΓΜΑ
    {
      "article_title": "Επίσημο Λογότυπο Ελληνικής Αστυνομίας",
      "provision_type": "ρύθμιση",
      "core_provision_summary": "Καθιερώνεται επίσημο λογότυπο Ελληνικής Αστυνομίας για ενιαία ταυτότητα και αναγνωρισιμότητα του Σώματος με αποκλειστική χρήση από τις υπηρεσίες της.",
      "key_themes": ["organization_identity", "official_logo"]
    }

    ΘΥΜΉΣΟΥ: Επιστρέφεις ΜΟΝΟ έγκυρο JSON."""
)

# ===========================================================================
# ACTIVELY USED PROMPTS - Error Handling & Retry
# Used in: retry.py for handling truncated outputs
# ===========================================================================

CONCISE_CONTINUATION_PROMPT = (
    "Η απάντησή σας διακόπηκε. Ολοκληρώστε άμεσα την τελευταία πρόταση με ελάχιστες λέξεις:"
)

# ===========================================================================
# LEGACY/UNUSED PROMPTS (kept for backward compatibility)
# These prompts were part of an earlier workflow design but are not actively used
# in the current modular_summarization pipeline
# ===========================================================================

STAGE2_COHESIVE_PROMPT = (
    "Οι παρακάτω είναι ατομικές περιλήψεις πολλαπλών άρθρων από μία ενιαία διαβούλευση. "
    "Παρακαλώ συνδυάστε τις σε ένα ενιαίο, συνεκτικό και περιεκτικό κείμενο στα Ελληνικά που να αποτυπώνει τα κύρια σημεία και τον ευρύτερο στόχο του νομοσχεδίου.\n"
    "Χρησιμοποιήστε απλή, μη τεχνική γλώσσα ώστε να γίνεται κατανοητό από το γενικό κοινό.\n"
    "Στοχεύστε σε περίπου 350–400 λέξεις συνολικά οργανωμένες σε 6–7 μικρές παραγράφους."
)

STAGE2_THEMES_PROMPT = (
    "Αξιοποιώντας τις περιλήψεις των άρθρων που ακολουθούν, καταγράψτε τα κύρια θέματα (π.χ. φορολογία, εργασιακά, προστασία δεδομένων) που επηρεάζουν τους πολίτες.\n"
    "Παρουσιάστε τα σε μορφή λίστας κουκίδων. Για κάθε θέμα δώστε μία σύντομη πρόταση που εξηγεί τον τρόπο με τον οποίο επηρεάζονται οι πολίτες.\n"
    "Χρησιμοποιήστε σαφή και απλή διατύπωση χωρίς νομική ορολογία."
)

STAGE2_PLAN_PROMPT = (
    "Με βάση τις παραπάνω περιλήψεις, σκιαγραφήστε ένα ΣΧΕΔΙΟ ΑΦΗΓΗΣΗΣ με 6–7 ενότητες.\n"
    "Κάθε ενότητα πρέπει να έχει: (α) έναν σύντομο περιγραφικό ΤΙΤΛΟ και (β) 1–2 προτάσεις περιγραφής.\n"
    "Ακολουθήστε δομή Αρχή – Μέση – Τέλος ώστε να διευκολύνεται η κατανόηση της συνολικής ιστορίας του νομοσχεδίου από τον αναγνώστη."
)

STAGE3_EXPOSITION_PROMPT = (
    "Χρησιμοποιώντας (1) τη Συνολική Περίληψη, (2) τα Κύρια Θέματα και (3) το Σχέδιο Αφήγησης, συνθέστε ένα ουδέτερο και ενημερωτικό κείμενο στα Ελληνικά.\n"
    "Το κείμενο θα αποτελέσει ενημερωτικό άρθρο για πολίτες χωρίς νομικές γνώσεις, οπότε απαιτείται απλή γλώσσα και σαφής ροή.\n"
    "Μήκος στόχος: ~600 λέξεις, κατανεμημένες σε λογικές παραγράφους που ακολουθούν το σχέδιο αφήγησης.\n"
    "Αποφύγετε jargon και προσωπικά σχόλια· διατηρήστε ουδέτερο τόνο."
)

SHORTENING_CORRECTION_PROMPT = (
    "Η περίληψη είναι υπερβολικά μεγάλη ή ατελής. Δημιουργήστε μια νέα, συντομότερη περίληψη, επικεντρωμένη στα κυριότερα σημεία:"
)

# Legacy static prompts for Stage 3 narrative planning (replaced by STAGE3_PLAN_DYN_PROMPT)
STAGE3_PLAN_PROMPT_A = """[SCHEMA:NARRATIVE_PLAN]\n**Ρόλος (Persona):**
Είστε ένας διακεκριμένος δημοσιογράφος, με πολυετή εμπειρία στην κάλυψη νομοθετικού έργου για μεγάλα ειδησεογραφικά μέσα. Το πάθος σας είναι η προάσπιση της δημοκρατίας μέσω της έγκυρης ενημέρωσης. Στόχος σας είναι να "μεταφράζετε" πολύπλοκες νομοθετικές αλλαγές σε απλή, κατανοητή και συνεκτική γλώσσα για το ευρύ κοινό.

**Οδηγίες:**
Σας παρέχονται τα επίσημα κείμενα «Σκοπός» ή/και «Αντικείμενο» για ένα Μέρος της νομοθεσίας, καθώς και οι περιλήψεις των κεφαλαίων που το απαρτίζουν. Δημιουργήστε ένα δομημένο αφηγηματικό σχέδιο σε μορφή JSON.

Επιστρέφετε **μόνο** έγκυρο JSON, κανέναν άλλον χαρακτήρα πριν ή μετά:

{
  "overall_narrative_arc": "Μία πρόταση που συνοψίζει το συνολικό αφηγηματικό τόξο του Μέρους",
  "protagonist": "Ο κύριος φορέας/θεσμός/έννοια που επηρεάζεται (π.χ. πολίτες, ΑΑΔΕ, επιχειρήσεις)",
  "problem": "Το πρόβλημα που επιχειρεί να λύσει αυτό το Μέρος του νόμου",
  "narrative_sections": [
    {
      "section_title": "Περιεκτικός τίτλος",
      "section_role": "Περιγραφή του σκοπού αυτής της ενότητας στη συνολική αφήγηση",
      "source_chapters": [0, 1]
    }
  ]
}

ΟΔΗΓΙΕΣ:
- overall_narrative_arc: Μία συνοπτική πρόταση για τη συνολική ιστορία
- protagonist: Ποιος επηρεάζεται κυρίως από τις αλλαγές
- problem: Τι πρόβλημα λύνει αυτό το νομοθετικό Μέρος
- narrative_sections: Λίστα 3-6 θεματικών ενοτήτων, καθεμία με:
  * section_title: Σύντομος περιγραφικός τίτλος (max 10 λέξεις)
  * section_role: Πώς αυτή η ενότητα συμβάλλει στη συνολική αφήγηση
  * source_chapters: Indices των κεφαλαίων που περιλαμβάνει αυτή η ενότητα

ΘΥΜΉΣΟΥ: Επιστρέφεις ΜΟΝΟ έγκυρο JSON."""

STAGE3_PLAN_PROMPT_B = """[SCHEMA:NARRATIVE_PLAN]\n**Ρόλος (Persona):**
Είστε ένας διακεκριμένος δημοσιογράφος, με πολυετή εμπειρία στην κάλυψη νομοθετικού έργου για μεγάλα ειδησεογραφικά μέσα. Το πάθος σας είναι η προάσπιση της δημοκρατίας μέσω της έγκυρης ενημέρωσης. Στόχος σας είναι να "μεταφράζετε" πολύπλοκες νομοθετικές αλλαγές σε απλή, κατανοητή και συνεκτική γλώσσα για το ευρύ κοινό.

**Οδηγίες:**
Σας παρέχονται οι περιλήψεις των κεφαλαίων που απαρτίζουν ένα Μέρος της νομοθεσίας. Δημιουργήστε ένα δομημένο αφηγηματικό σχέδιο σε μορφή JSON βασιζόμενοι μόνο στις περιλήψεις των κεφαλαίων.

Επιστρέφετε **μόνο** έγκυρο JSON, κανέναν άλλον χαρακτήρα πριν ή μετά:

{
  "overall_narrative_arc": "Μία πρόταση που συνοψίζει το συνολικό αφηγηματικό τόξο του Μέρους",
  "protagonist": "Ο κύριος φορέας/θεσμός/έννοια που επηρεάζεται (π.χ. πολίτες, ΑΑΔΕ, επιχειρήσεις)",
  "problem": "Το πρόβλημα που επιχειρεί να λύσει αυτό το Μέρος του νόμου",
  "narrative_sections": [
    {
      "section_title": "Περιεκτικός τίτλος",
      "section_role": "Περιγραφή του σκοπού αυτής της ενότητας στη συνολική αφήγηση",
      "source_chapters": [0, 1]
    }
  ]
}

ΟΔΗΓΙΕΣ:
- overall_narrative_arc: Μία συνοπτική πρόταση για τη συνολική ιστορία
- protagonist: Ποιος επηρεάζεται κυρίως από τις αλλαγές
- problem: Τι πρόβλημα λύνει αυτό το νομοθετικό Μέρος (εξάγετε το από τις περιλήψεις)
- narrative_sections: Λίστα 3-6 θεματικών ενοτήτων, καθεμία με:
  * section_title: Σύντομος περιγραφικός τίτλος (max 10 λέξεις)
  * section_role: Πώς αυτή η ενότητα συμβάλλει στη συνολική αφήγηση
  * source_chapters: Indices των κεφαλαίων που περιλαμβάνει αυτή η ενότητα

ΘΥΜΉΣΟΥ: Επιστρέφεις ΜΟΝΟ έγκυρο JSON."""

# ===========================================================================
# PUBLIC REGISTRY & FACTORY
# ===========================================================================
PROMPTS: Dict[str, str] = {
    # Stage 1 - Article summarization
    "stage1_article": STAGE1_PROMPT,
    
    # Stage 2 - Chapter summarization (actively used)
    "stage2_chapter": STAGE2_CHAPTER_PROMPT,
    
    # Stage 3 - Part summarization (legacy single-stage)
    "stage3_part": STAGE3_PART_PROMPT,
    "stage3_part_skopos": STAGE3_PART_SKOPOS_PREFIX,
    "stage3_part_antikeimeno": STAGE3_PART_ANTIKEIMENO_PREFIX,
    
    # Stage 3 Expansion - Two-stage narrative summarization (actively used)
    "stage3_plan_dyn": STAGE3_PLAN_DYN_PROMPT,  # Dynamic beat count
    "stage3_single_chapter": STAGE3_SINGLE_CHAPTER_PROMPT,  # Fast-track single chapter
    "stage3_synth": STAGE3_SYNTH_PROMPT,    # Chunk synthesis
    "stage3_critique": STAGE3_CRITIQUE_PROMPT,
    "stage3_polish": JOURNALISTIC_POLISH_PROMPT,
    
    # Law classification prompts (actively used)
    "law_mod_json_mdata": LAW_MOD_JSON_PROMPT_W_MDATA,
    "law_new_json": LAW_NEW_JSON_PROMPT,
    
    # Error handling (actively used)
    "concise_continuation": CONCISE_CONTINUATION_PROMPT,
    
    # Legacy/unused prompts (kept for backward compatibility)
    "stage2_cohesive": STAGE2_COHESIVE_PROMPT,
    "stage2_themes": STAGE2_THEMES_PROMPT,
    "stage2_plan": STAGE2_PLAN_PROMPT,
    "stage3_exposition": STAGE3_EXPOSITION_PROMPT,
    "shortening_correction": SHORTENING_CORRECTION_PROMPT,
    "stage3_plan_a": STAGE3_PLAN_PROMPT_A,  # With Σκοπός/Αντικείμενο
    "stage3_plan_b": STAGE3_PLAN_PROMPT_B,  # Without Σκοπός/Αντικείμενο
}

def get_prompt(key: str) -> str:
    """Return prompt text; raises KeyError if not found."""
    return PROMPTS[key]

__all__ = list(PROMPTS.keys()) + [
    "PROMPTS",
    "get_prompt",
]

# NOTE: Retry logic moved to `retry.py` to decouple generation heuristics from templates.