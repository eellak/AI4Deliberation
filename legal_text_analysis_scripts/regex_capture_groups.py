# ✅ STRUCTURED REGEXES FOR LEGAL REFERENCES (with named capturing groups)

# 1. ΝΟΜΟΙ, Α.Ν., Κ.Ν., ΠΑΛΙΟΙ ΝΟΜΟΙ
LAW_REGEX_PATTERN = r"""
(?ix)  # Case-insensitive, verbose
(?!\s*\[?\s*ν\.δ)(?!\s*\[?\s*Ν\.Δ)         # Exclude νομοθετικά διατάγματα
\[?                                              # Optional opening bracket
(?P<type>                                          # Type of law
    ν\.|Ν\.|                                     # Standard law
    α\.ν\.|Α\.Ν\.|                              # Emergency law
    κ\.ν\.|Κ\.Ν\.|                              # Codified law
    ν\.?\s*[Α-Ω]+|Ν\.?\s*[Α-Ω]+|               # Prefixed law: ν. ΓΩΠΣΤ
    v\.|
    νόμου                                        # ADDED: to capture "νόμου" or "Νόμου" (case-insensitive)
)
\s*
(?P<number>\d+)                                   # Law number
\s*/\s*
(?P<year>\d{4})                                   # Year
(?:[\s,]*\(?(?P<fek_series>Α'?'|Α`?'|A'?')\s*(?P<fek_number>\d+)\)?)?  # Optional FEK info
\]?                                              # Optional closing bracket
"""

# 2. ΠΡΟΕΔΡΙΚΑ ΔΙΑΤΑΓΜΑΤΑ
PRESIDENTIAL_DECREE_REGEX_PATTERN = r"""
(?ix)
(?P<prefix>π\.δ\.|Π\.Δ\.|Π\.δ\.|πδ|π\.δ|προεδρικ[οό] διάταγμα)
(?:
    \s*(?P<number>\d+)\s*/\s*(?P<year_num>\d{4})                         # Standard format with year_num
|
    \s+της\s+
    (?P<date1_day>\d{1,2}(?:ης)?)                                       # e.g. 28ης
    (?:\.|\s+|η)?
    (?P<date1_month>[α-ωΑ-Ω]+\d{1,2})                                  # e.g. Ιουλίου or 2
    (?:\s*/\s*                                                   # Optional dual date
        (?P<date2_day>\d{1,2}(?:ης)?)
        (?:\.|\s+|η)?
        (?P<date2_month>[α-ωΑ-Ω]+\d{1,2})
    )?
    (?:\.|\s+)?(?P<year_date>\d{4})                                   # Year in date format as year_date
)
"""

# 3. ΥΠΟΥΡΓΙΚΕΣ / ΚΟΙΝΕΣ ΥΠΟΥΡΓΙΚΕΣ ΑΠΟΦΑΣΕΙΣ
MINISTERIAL_DECISION_REGEX_PATTERN = r"""
(?ix)   # case-insensitive, verbose

# Optional capturing group for the "paragraph" prefix we want to exclude
(?P<undesired_prefix>(?:παρ(?:άγραφος|άγρ)?\.\s*)\d+\s+)? 

\b                                         # Start at word boundary

(?:                                        # GROUP A: [type] before [reference]
    (?P<type1>
        κοιν[ηής]{1,2}\s+υπουργικ[ηής]{1,2}\s+απόφασ[ηε]|
        υπουργικ[ηής]{1,2}\s+απόφασ[ηε]|
        Κ\.?Υ\.?Α\.?|
        ΚΥΑ|
        Υ\.?Α\.?|
        ΥΑ
    )
    \s+
    (?P<ref1>
        (?:υπ\'?\s*αρ(?:\.|ιθμ\.)?\s*)?     # optional prefix e.g. υπ\' αριθμ.
        (?:οικ\.?\s*)?                       # optional "οικ." prefix
        # Simplified Core identifier:
        (?P<id1>
            (?=[A-ZΑ-Ω0-9()/.\-‐−\s]*[0-9/])  # Lookahead: ensures a digit or slash in the id (incl. spaces)
            (?:οικ\.?\s*|[A-ZΑ-Ω0-9()/.\-‐−])+ # Matches sequences of allowed chars, οικ. (now allows internal spaces more freely)
            # The ADA part is now separate and clearly at the end of id1 logic
        )
        (?:\s*\(ΑΔΑ:\s*[A-ZΑ-Ω0-9\-‐−]+\))? # Optional ADA part, moved to follow the main id1
        # Optional FEK information
        (?:
            \s* [,(]? \s*
            (?:ΦΕΚ|[ΦΦ]\.[ΕΕ]\.[ΚΚ]\.|[ΒΒ]\.?)? \s*
            (?P<fek_series1>[Α-ΩA-ZΆ-Ώά-ώ\'’`]+)? \s*
            (?P<fek_number1>\d+)
            (?:\s*[/-]\s*(?P<fek_year1>\d{4}))? 
            \s* \)?
        )?
    )
)

|

(?:                                        # GROUP B: [reference] before [type]
    (?P<ref2>
        (?:υπ\'?\s*αρ(?:\.|ιθμ\.)?\s*)?
        (?:οικ\.?\s*)?
        # Simplified Core identifier:
        (?P<id2>
            (?=[A-ZΑ-Ω0-9()/.\-‐−\s]*[0-9/])  # Lookahead: ensures a digit or slash in the id (incl. spaces)
            (?:οικ\.?\s*|[A-ZΑ-Ω0-9()/.\-‐−])+ # Matches sequences of allowed chars, οικ.
        )
        (?:\s*\(ΑΔΑ:\s*[A-ZΑ-Ω0-9\-‐−]+\))? # Optional ADA part, moved to follow main id2
        # Optional FEK information
        (?:
            \s* [,(]? \s*
            (?:ΦΕΚ|[ΦΦ]\.[ΕΕ]\.[ΚΚ]\.|[ΒΒ]\.?)? \s*
            (?P<fek_series2>[Α-ΩA-ZΆ-Ώά-ώ\'’`]+)? \s*
            (?P<fek_number2>\d+)
            (?:\s*[/-]\s*(?P<fek_year2>\d{4}))? 
            \s* \)?
        )?
    )
    \s+
    (?P<type2>
        κοιν[ηής]{1,2}\s+υπουργικ[ηής]{1,2}\s+απόφασ[ηε]|
        υπουργικ[ηής]{1,2}\s+απόφασ[ηε]|
        Κ\.?Υ\.?Α\.?|
        ΚΥΑ|
        Υ\.?Α\.?|
        ΥΑ
    )
)

\b                                         # End at word boundary

"""


# INITIAL VERSION
# MINISTERIAL_DECISION_REGEX_PATTERN = r"""
# (?ix)   # case-insensitive, verbose

# (?<!(?:παρ(?:άγραφος|άγρ)?\\.\\s*)\\d+\\s+) # Negative lookbehind for "παρ. X "
# \\b                                         # Start at word boundary

# (?:                                        # GROUP A: [type] before [reference]
#     (?P<type1>
#         κοιν[ηής]{1,2}\\s+υπουργικ[ηής]{1,2}\\s+απόφασ[ηε]|
#         υπουργικ[ηής]{1,2}\\s+απόφασ[ηε]|
#         Κ\\.?Υ\\.?Α\\.?|
#         ΚΥΑ|
#         Υ\\.?Α\\.?|
#         ΥΑ
#     )
#     \\s+
#     (?P<ref1>
#         (?:υπ\\\'?\\s*αρ(?:\\.|ιθμ\\.)?\\s*)?     # optional prefix e.g. υπ\\\' αριθμ.
#         (?:οικ\\.?\\s*)?                       # optional "οικ." prefix
#         # Core identifier: must contain at least one digit or slash
#         (?P<id1>
#             (?=[A-ZΑ-Ω0-9()/.\\-‐−]*[0-9/]) # Lookahead: must contain a digit or slash
#             (?:(?:[A-ZΑ-Ω0-9()/.\\-‐−]+|\\([A-ZΑ-Ω0-9()/.\\-‐−]+\\))+)  # First ID part
#             (?: # Optional subsequent ID parts (zero or more)
#                 \\s+(?:οικ\\.?\\s*)? # Separator: one or more spaces, then optional \'οικ.\'
#                 (?:(?:[A-ZΑ-Ω0-9()/.\\-‐−]+|\\([A-ZΑ-Ω0-9()/.\\-‐−]+\\))+) # The subsequent ID part
#             )*
#             (?:\\s*\\(ΑΔΑ:\\s*[A-ZΑ-Ω0-9\\-‐−]+\\))? # Optional ADA part
#         )
#         # Optional FEK information (NOW UNCOMMENTED)
#         (?:
#             \\s* [,(]? \\s*
#             (?:ΦΕΚ|[ΦΦ]\\.[ΕΕ]\\.[ΚΚ]\\.|[ΒΒ]\\.?)? \\s*
#             (?P<fek_series1>[Α-ΩA-ZΆ-Ώά-ώ\\\'’`]+)? \\s*
#             (?P<fek_number1>\\d+)
#             (?:\\s*[/-]\\s*(?P<fek_year1>\\d{4}))? # Use [/-] for separator
#             \\s* \\)?
#         )?
#     )
# )

# |

# (?:                                        # GROUP B: [reference] before [type]
#     (?P<ref2>
#         (?:υπ\\\'?\\s*αρ(?:\\.|ιθμ\\.)?\\s*)?
#         (?:οικ\\.?\\s*)?
#         # Core identifier: must contain at least one digit or slash
#         (?P<id2>
#             (?=[A-ZΑ-Ω0-9()/.\\-‐−]*[0-9/]) # Lookahead: must contain a digit or slash
#             (?:(?:[A-ZΑ-Ω0-9()/.\\-‐−]+|\\([A-ZΑ-Ω0-9()/.\\-‐−]+\\))+)  # First ID part
#             (?: # Optional subsequent ID parts (zero or more)
#                 \\s+(?:οικ\\.?\\s*)? # Separator: one or more spaces, then optional \'οικ.\'
#                 (?:(?:[A-ZΑ-Ω0-9()/.\\-‐−]+|\\([A-ZΑ-Ω0-9()/.\\-‐−]+\\))+) # The subsequent ID part
#             )*
#             (?:\\s*\\(ΑΔΑ:\\s*[A-ZΑ-Ω0-9\\-‐−]+\\))? # Optional ADA part
#         )
#         # Optional FEK information (NOW UNCOMMENTED)
#         (?:
#             \\s* [,(]? \\s*
#             (?:ΦΕΚ|[ΦΦ]\\.[ΕΕ]\\.[ΚΚ]\\.|[ΒΒ]\\.?)? \\s*
#             (?P<fek_series2>[Α-ΩA-ZΆ-Ώά-ώ\\\'’`]+)? \\s*
#             (?P<fek_number2>\\d+)
#             (?:\\s*[/-]\\s*(?P<fek_year2>\\d{4}))? # Use [/-] for separator
#             \\s* \\)?
#         )?
#     )
#     \\s+
#     (?P<type2>
#         κοιν[ηής]{1,2}\\s+υπουργικ[ηής]{1,2}\\s+απόφασ[ηε]|
#         υπουργικ[ηής]{1,2}\\s+απόφασ[ηε]|
#         Κ\\.?Υ\\.?Α\\.?|
#         ΚΥΑ|
#         Υ\\.?Α\\.?|
#         ΥΑ
#     )
# )

# \\b                                         # End at word boundary

# """