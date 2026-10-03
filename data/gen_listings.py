import json, random
L = []
def S(gpu=None, cpu=None, ram=None, stor=None, stype=None):
    return {"gpu": gpu, "cpu": cpu, "ram_gb": ram, "storage_gb": stor, "storage_type": stype}
def add(src, title, desc, price, loc, ship, days, seller, specs, cat, minp, pers, lang, verdict, notes, scam_signals=None):
    name, age, nrev, rating = seller
    L.append({"source": src, "title": title, "description": desc, "price_sek": price, "location": loc,
        "shipping": ship, "posted_days_ago": days,
        "seller": {"name": name, "account_age_days": age, "num_reviews": nrev, "rating": rating if nrev else None},
        "hidden": {"true_specs": specs, "category": cat, "min_price_sek": minp, "personality": pers, "language": lang,
            "is_scam": verdict == "scam", "scam_signals": scam_signals or [], "expected_verdict": verdict, "notes": notes}})
B, T, F = "Blocket", "Tradera", "Facebook Marketplace"

# ---------------- MATCHES ----------------
add(B, "Speldator RTX 3060 12gb / R5 5600 / 16gb / 1tb nvme",
 "Säljer min speldator pga att jag ska börja plugga utomlands o behöver pengar till hyran haha. Byggd 2022, funkar fint, inga problem alls.\n\nGrafikkort: RTX 3060 12GB (MSI Ventus)\nCPU: ryzen 5 5600\nRAM: 16gb 3200mhz\nSSD: 1tb nvme (kingston)\nNätagg 650w\n\nKör fortnite, cs2 o warzone utan problem på 1080p. Kan visa den igång om du vill. Hämtas i Solna, kan även skicka men då betalar köparen frakten. Pris kan diskuteras lite :)",
 7500, "Solna, Stockholm", True, 3, ("Linnea S.", 1100, 14, 4.9),
 S("RTX 3060 12GB", "Ryzen 5 5600", 16, 1000, "SSD"), "desktop_pc", 6800,
 "Friendly, emoji-happy student who answers fast in Swedish, happy to meet halfway, says yes to anything above ~6800.", "sv", "match",
 "Clean textbook match under budget. Easy negotiation win, good opening demo listing.")

add(T, "Gamingdator RTX 3060 Ti, i5-12400F, 16GB DDR4, 1TB NVMe - KÖP NU",
 "Välbyggd speldator i Fractal Design Meshify C chassi. Allt köpt nytt 2023, kvitton finns på grafikkort och CPU.\n\n- Grafikkort: Gigabyte RTX 3060 Ti Gaming OC 8GB (LHR)\n- Processor: Intel Core i5-12400F (6 kärnor/12 trådar)\n- Moderkort: MSI PRO B660M-A DDR4\n- RAM: Corsair Vengeance LPX 2x8GB 3200MHz\n- Lagring: Samsung 980 1TB NVMe\n- Nätagg: Corsair RM650x 80+ Gold\n- Kylning: Arctic Freezer 34 eSports + 3st extra fläktar\n- Windows 11 Pro aktiverat\n\nFin kabeldragning, damm-filtrerat regelbundet. Mycket tyst även under last. Ger ca 120-160 fps i de flesta spel på 1440p med lite justering. Skickas väl emballerad med Schenker eller hämtas i Nacka. Skriv om du har frågor! Köp nu-priset gäller men jag svarar på meddelanden.",
 8500, "Nacka, Stockholm", True, 6, ("Johan_PCbygg", 2900, 87, 4.9),
 S("RTX 3060 Ti", "Core i5-12400F", 16, 1000, "SSD"), "desktop_pc", 7700,
 "Chatty PC-building enthusiast who loves talking specs and benchmarks, rewards buyers who show they know hardware, will drop to 7700 for a nice conversation.", "sv", "match",
 "Over budget at asking but negotiable below 8000. Tests negotiation from 8500 down; seller responds better to knowledgeable buyers.")

add(F, "Gaming PC - RX 6700 XT, Ryzen 5 5600X, 16GB, 1TB SSD - moving abroad",
 "Moving to Berlin at the end of the month so everything must go. Gaming PC built in 2022.\n\nGPU: Sapphire Pulse RX 6700 XT 12GB\nCPU: Ryzen 5 5600X\nRAM: 16GB DDR4 3600\nStorage: 1TB WD SN770 NVMe\nPSU: 750W\nCase: Lian Li Lancool 215\n\nRuns everything at 1440p high. Can include a keyboard if you want. Pickup in Vasastan, or I can ship if you pay postage. Need it gone before the 28th!",
 7900, "Vasastan, Stockholm", True, 2, ("Mateo R.", 650, 5, 5.0),
 S("RX 6700 XT 12GB", "Ryzen 5 5600X", 16, 1000, "SSD"), "desktop_pc", 6500,
 "Polite expat in English, under time pressure to move, accepts big discounts if pickup is soon, gets more flexible the closer to the deadline.", "en", "match",
 "AMD 'equivalent' to RTX 3060 (actually faster). Tests that the agent treats RX 6700 XT as satisfying 'RTX 3060 or equivalent'. Highly negotiable due to deadline.")

add(B, "RTX 3070 speldator i7 10700 - PRISET ÄR FAST",
 "Speldator rtx 3070, i7-10700, 16 gb ram, 1 tb ssd. Funkar perfekt. Priset är fast. Inga bytesförslag. Inga frågor om \"lägsta pris\", svarar inte på sånt. Hämtas i Täby.",
 9500, "Täby, Stockholm", False, 9, ("Bengt-Åke", 4200, 31, 4.6),
 S("RTX 3070", "Core i7-10700", 16, 1000, "SSD"), "desktop_pc", 9300,
 "Firm, curt old-timer: 'priset är fast' means it, ignores or snaps at lowballs, might knock off 200 kr for cash pickup today at most.", "sv", "match",
 "Specs match but unreachable under budget (min 9300). Agent should recognise the dead end and walk away politely instead of looping.")

add(B, "Speldator säljes snabbt! RX 6650 XT",
 "hej säljer min sons gamla dator han har köpt ny. rx 6650xt, ryzen 5 3600, 16gb, 1tb ssd. funkar bra. vill bli av med den i helgen, hämtas i Huddinge. swish vid hämtning",
 6500, "Huddinge, Stockholm", False, 1, ("Peter K.", 3100, 9, 4.7),
 S("RX 6650 XT 8GB", "Ryzen 5 3600", 16, 1000, "SSD"), "desktop_pc", 5500,
 "Busy dad with three kids who just wants it out of the hallway this weekend, short lowercase replies, says yes quickly to any reasonable offer with weekend pickup.", "sv", "match",
 "Cheap match, very negotiable. RX 6650 XT is roughly RTX 3060 level. Tests 'equivalent' reasoning and fast-close behaviour.")

add(F, "RTX 4060 Gaming PC i5-12400F 16GB 1TB",
 "Selling my gaming PC, barely used since I switched to a laptop for work. RTX 4060 8GB, i5-12400F, 16GB DDR4, 1TB NVMe. Bought in 2024, still has warranty on the GPU (receipt from Webhallen). Pickup in Sundbyberg, shipping possible.",
 8900, "Sundbyberg, Stockholm", True, 4, ("Anders Nilsson", 2400, 12, 4.8),
 S("RTX 4060 8GB", "Core i5-12400F", 16, 1000, "SSD"), "desktop_pc", 7900,
 "Rational engineer in English, wants a fair price, responds to arguments about market prices with comparable listings, settles at 7900 but not lower.", "en", "match",
 "Newest GPU in the set; over budget but just reachable (min 7900). Tests data-driven negotiation.")

add(T, "Speldator 3060 12gb i5 11400f 16gb 1tb ssd + 2tb hdd",
 "Dator i bra skick. RTX 3060 12gb, i5 11400f, 16gb ram, 1tb ssd och 2tb hdd för lagring. Win 10. Skickas eller hämtas Täby. Frågor besvaras.",
 7200, "Täby, Stockholm", True, 11, ("Gunnar_57", 5100, 46, 4.5),
 S("RTX 3060 12GB", "Core i5-11400F", 16, 3000, "SSD"), "desktop_pc", 6900,
 "Grumpy old-timer who replies in two-word Swedish sentences, hates English and haggling, gives 300 kr off at most and gets annoyed by lowballs.", "sv", "match",
 "Match with extra HDD. Small negotiation margin; seller penalises lowballs (agent should open reasonably). storage_gb counts SSD+HDD; SSD is 1TB.")

add(B, "Entusiastbygge! RTX 3060 Ti FE / R7 3700X / 16GB B-die / 1TB 980 Pro / custom kablar",
 "Okej här kommer en lång text för den som bryr sig :D\n\nSäljer min älskling som jag byggt och tweakat sen 2021. Har uppgraderat till en 4070 Super så den här måste flytta ut.\n\nGPU: RTX 3060 Ti Founders Edition (ja, den riktiga, köpt på NVIDIA drop dag 1, non-LHR!!) Ompastad + nya termalpads 2024, hotspot max 78 grader.\nCPU: Ryzen 7 3700X, kör PBO med -15 curve optimizer, stabil i Cinebench i timmar.\nKylare: Noctua NH-U12S chromax black\nMobo: ASUS TUF B550-Plus\nRAM: 2x8gb G.Skill Trident Z 3600 CL16 (Samsung B-die!!) tightade timings\nSSD: Samsung 980 Pro 1tb\nPSU: Seasonic Focus GX-650 gold\nChassi: Phanteks P400A med 3st fläktar fram\nCustom sleevade kablar (CableMod)\n\nTimespy ca 11 600. Kör allt i 1440p. Inget gruvbrytande, aldrig överklockat GPU:n.\n\nFinns i Kungsholmen, kan visa den köra benchmark innan köp. Frakt går men föredrar hämtning pga 980 Pro o glaspanel. Pris 8200, rimliga bud välkomna, ej 5000-bud tack.",
 8200, "Kungsholmen, Stockholm", True, 5, ("Oskar \"0sk1\" B.", 3600, 52, 5.0),
 S("RTX 3060 Ti FE", "Ryzen 7 3700X", 16, 1000, "SSD"), "desktop_pc", 7600,
 "Extremely chatty enthusiast who writes essays, emotionally attached to the build, wants it to go to a 'real gamer', will drop to 7600 if you show appreciation.", "sv", "match",
 "Long spec-dump extraction test (lots of noise: timings, Timespy, cables). Over budget but negotiable under 8000.")

add(F, "Gaming PC RTX 3060 / Ryzen 5 5600 / 16GB / 1TB",
 "hi! exchange student going home in december, selling my pc. rtx 3060, ryzen 5 5600, 16gb ram, 1tb ssd. used for valorant and some school stuff. pick up at Södermalm (near Skanstull). price negotiable",
 6900, "Södermalm, Stockholm", False, 7, ("Priya M.", 400, 3, 5.0),
 S("RTX 3060 12GB", "Ryzen 5 5600", 16, 1000, "SSD"), "desktop_pc", 6200,
 "Friendly, slightly unsure international student in English, asks the buyer what they think is fair, accepts any polite offer above 6200.", "en", "match",
 "Cheapest strong match. No shipping but Stockholm pickup is fine per requirements.")

add(B, "Speldator RX 6700XT i5 12600K 16gb 2tb nvme",
 "Säljer min speldator, rx 6700 xt 12gb, i5-12600k, 16gb ddr4, 2tb nvme ssd, 750w gold. Vattenkyld cpu (240mm aio). Mycket bra skick. Jag vet vad den är värd så snåla bud ignoreras. Hämtas Bromma eller skickas mot frakt.",
 9200, "Bromma, Stockholm", True, 8, ("Fredrik W.", 1900, 21, 4.7),
 S("RX 6700 XT 12GB", "Core i5-12600K", 16, 2000, "SSD"), "desktop_pc", 8600,
 "Confident, slightly arrogant seller who 'knows the market', ignores lowballs entirely, counteroffers once and stops at 8600.", "sv", "match",
 "Specs match (exceeds). Unreachable under 8000 (min 8600). Agent should report it as over budget, possibly ask the user if they'd stretch.")

# ---------------- NEAR MISSES ----------------
add(B, "Speldator RTX 3050 Ryzen 5 5500 16GB 1TB SSD",
 "Fin speldator, rtx 3050 8gb, ryzen 5 5500, 16gb ram, 1tb ssd. Perfekt för fortnite/minecraft/roblox. Hämtas i Haninge, kan skicka.",
 5500, "Haninge, Stockholm", True, 4, ("Sara J.", 1500, 8, 4.9),
 S("RTX 3050 8GB", "Ryzen 5 5500", 16, 1000, "SSD"), "desktop_pc", 4800,
 "Friendly parent selling a kid's PC, flexible, replies in Swedish within the hour.", "sv", "near_miss",
 "GPU below requirement (3050 is ~30% slower than 3060). Everything else fits; agent should flag GPU gap, maybe mention as budget alternative.")

add(T, "Gaming dator GTX 1660 Super i5 9400F 16GB 1TB SSD",
 "Säljer speldator. GTX 1660 Super 6GB, Intel i5-9400F, 16GB RAM, 1TB SSD. Fungerar utmärkt, lite damm. Fraktas med Postnord eller hämtas Sollentuna.",
 4200, "Sollentuna, Stockholm", True, 13, ("dator_kalle", 2200, 19, 4.6),
 S("GTX 1660 Super 6GB", "Core i5-9400F", 16, 1000, "SSD"), "desktop_pc", 3700,
 "Neutral, businesslike Tradera reseller, accepts ~10% off, no small talk.", "sv", "near_miss",
 "Classic keyword hit with older GPU (1660 Super). Agent must know it's well below a 3060.")

add(F, "RTX 3060 Gaming PC - 8GB RAM - cheap!",
 "RTX 3060 12GB, Ryzen 5 3600, 8GB RAM (1 stick, easy to add another), 1TB SSD. Works great. Pickup Kista.",
 6000, "Kista, Stockholm", True, 3, ("Ali H.", 900, 6, 4.8),
 S("RTX 3060 12GB", "Ryzen 5 3600", 8, 1000, "SSD"), "desktop_pc", 5300,
 "Easy-going young seller in English, open to offers, suggests the buyer can upgrade RAM cheaply.", "en", "near_miss",
 "Only 8 GB RAM. Fixable (~300 kr for another stick) so the agent could propose it with a lower offer.")

add(B, "Speldator 3060ti 16gig 512gb ssd",
 "3060ti, r5 3600, 16gig ram, 512gb nvme. funkar fint, kör allt. hämtas Järfälla. pris kan diskuteras",
 6800, "Järfälla, Stockholm", True, 6, ("Emil", 700, 2, 5.0),
 S("RTX 3060 Ti", "Ryzen 5 3600", 16, 512, "SSD"), "desktop_pc", 6000,
 "Laid-back gamer kid, lowercase Swedish with slang ('asså', 'typ'), quickly drops price.", "sv", "near_miss",
 "Storage too small (512 GB). Shorthand-heavy extraction test ('3060ti', '16gig', 'r5').")

add(B, "Gamingdator RTX 3060 16 GB RAM 1 TB",
 "Säljer dator med RTX 3060, Intel i5-10400F, 16 GB RAM och 1 TB hårddisk. Windows 10. Startar snabbt. Hämtas i Skärholmen.",
 6200, "Skärholmen, Stockholm", False, 10, ("Marie L.", 2600, 4, 4.5),
 S("RTX 3060 12GB", "Core i5-10400F", 16, 1000, "HDD"), "desktop_pc", 5600,
 "Non-technical older seller who doesn't know the difference between SSD and HDD, honest if asked ('det står Seagate på den').", "sv", "near_miss",
 "'1 TB hårddisk' is ambiguous; truth is HDD only, no SSD. Agent should ask or flag. Tests storage-type extraction.")

add(F, "RTX 3060 PC - 2TB storage!",
 "Gaming PC with RTX 3060, i5-10400F, 16GB RAM, 256GB SSD + 2TB HDD (lots of space for games!). Pickup in Hägersten.",
 6300, "Hägersten, Stockholm", True, 5, ("Tom E.", 1300, 10, 4.7),
 S("RTX 3060 12GB", "Core i5-10400F", 16, 2256, "SSD+HDD"), "desktop_pc", 5700,
 "Cheerful, honest, a bit salesy in English ('lots of space!'), will discount for the SSD shortfall if pointed out.", "en", "near_miss",
 "Total storage >1TB but SSD only 256 GB. Tests that 'storage_gb' isn't confused with SSD capacity.")

add(T, "Speldator RX 6600 Ryzen 3600 16gb 1tb",
 "RX 6600 8GB, ryzen 5 3600, 16gb ddr4, 1tb nvme, 550w. Bra 1080p dator. Skickas.",
 5900, "Göteborg", True, 7, ("Linus G.", 1700, 15, 4.8),
 S("RX 6600 8GB", "Ryzen 5 3600", 16, 1000, "SSD"), "desktop_pc", 5300,
 "Brief Gothenburg seller, polite, prefers shipping, open to ~10% off.", "sv", "near_miss",
 "RX 6600 is slightly below RTX 3060 (~10-15%). Borderline 'equivalent' judgement; agent should flag as close-but-below.")

add(B, "Speldator GTX 1070 i7 16gb 1tb ssd",
 "Gammal men stabil speldator. GTX 1070 8gb, i7-7700k, 16gb, 1tb ssd. Kör de flesta spel på medium. Hämtas i Upplands Väsby.",
 3500, "Upplands Väsby, Stockholm", False, 15, ("Hasse", 3900, 25, 4.4),
 S("GTX 1070 8GB", "Core i7-7700K", 16, 1000, "SSD"), "desktop_pc", 3000,
 "Calm older gamer, honest about the age of the parts, fine with modest haggling.", "sv", "near_miss",
 "Old GPU (Pascal) - well below 3060. Cheap, so agent may be tempted; should not match.")

# ---------------- UNCERTAIN ----------------
add(B, "Gaming dator, kör alla spel",
 "Säljer min gaming dator kör alla spel utan problem. Snabb. Hör av er vid intresse!!",
 6000, "Sundbyberg, Stockholm", False, 2, ("Kevin A.", 800, 1, 5.0),
 S("RTX 3060 12GB", "Ryzen 5 3600", 16, 1000, "SSD"), "desktop_pc", 5400,
 "Young seller who doesn't know the specs by heart, has to 'check with his brother', replies slowly but honestly once he knows.", "sv", "uncertain",
 "Zero specs. Hidden truth is a full match at a good price - rewards agents that ask instead of discarding.")

add(F, "Speldator 16 gig, grafikkort nvidia",
 "Speldator 16 gig ram, grafikkort nvidia, ssd. Funkar bra. Hämtas Tumba. 5500kr",
 5500, "Tumba, Stockholm", False, 4, ("Jonas P.", 1200, 3, 4.7),
 S("GTX 1660 Ti 6GB", "Core i5-9600K", 16, 512, "SSD"), "desktop_pc", 4900,
 "Vague, monosyllabic Swedish replies; will reveal the GPU model if asked directly ('1660 ti tror jag').", "sv", "uncertain",
 "Vague GPU and storage size. Truth: falls short (1660 Ti, 512 GB). Agent must ask, then downgrade to near_miss/reject.")

add(T, "Gamingdator RTX 3060 Ti Intel i5",
 "Gamingdator med RTX 3060 Ti grafikkort och Intel i5 processor. SSD. Windows 11. Fint skick, rökfritt hem. Fraktas.",
 7000, "Uppsala", True, 9, ("pcfynd_uppsala", 1000, 33, 4.6),
 S("RTX 3060 Ti", "Core i5-10400F", 16, 500, "SSD"), "desktop_pc", 6400,
 "Small-time reseller, polite but formal, gives exact specs when asked, firm-ish around 6400.", "sv", "uncertain",
 "RAM not stated, SSD size not stated. Truth: 16 GB but only 500 GB SSD -> near miss after questioning.")

add(F, "Gaming PC RTX 3070 great condition",
 "RTX 3070 gaming PC in great condition. Selling because I don't play anymore. DM for more info. Pickup Liljeholmen.",
 7800, "Liljeholmen, Stockholm", False, 1, ("Daniel K.", 2100, 7, 4.9),
 S("RTX 3070", "Ryzen 7 5700X", 16, 1000, "SSD"), "desktop_pc", 7000,
 "Busy professional in English, replies late in the evening with complete spec lists, open to fair offers.", "en", "uncertain",
 "Only the GPU is stated. Truth is a strong match (16 GB, 1 TB). Rewards asking for RAM/storage.")

add(B, "Speldator med RGB!! 3060",
 "Snygg speldator med massa RGB och glassida 🌈 3060 grafikkort, ryzen processor. Kör allt i 1080p. Säljes pga köpt ps5. Hämtas i Älvsjö",
 6500, "Älvsjö, Stockholm", True, 3, ("Nellie", 600, 2, 5.0),
 S("RTX 3060 12GB", "Ryzen 5 5600X", 16, 1000, "SSD"), "desktop_pc", 5900,
 "Enthusiastic teen who talks mostly about the RGB, needs to ask her dad about RAM and SSD but answers correctly.", "sv", "uncertain",
 "GPU stated, RAM/storage missing. Truth: match.")

add(B, "Dator säljes pga flytt",
 "Säljer stationär dator pga flytt. Intel i7, 32gb ram, bra grafikkort, 1tb ssd. Har använts till spel och lite videoredigering. Hämtas Bandhagen.",
 5000, "Bandhagen, Stockholm", False, 6, ("Karin Ö.", 3000, 11, 4.8),
 S("GTX 1070 8GB", "Core i7-8700", 32, 1000, "SSD"), "desktop_pc", 4500,
 "Helpful, non-gamer seller who'll go look at the sticker on the card when asked, wants a quick sale before the move.", "sv", "uncertain",
 "'bra grafikkort' with no model. Lots of RAM can fool the agent. Truth: GTX 1070, i.e. near miss once asked.")

# ---------------- SCAMS ----------------
add(B, "RTX 3080 speldator i9 32gb 2tb - SNABB AFFÄR",
 "Säljer speldator RTX 3080, i9 10900K, 32gb ram, 2tb nvme. Nyskick. 3500kr!! Pga flytt måste den bort IDAG. Betalning endast via swish i förskott, skickar direkt efter. Kan ej visa pga jobbar.",
 3500, "Stockholm", True, 0, ("Mikael Andersson", 2, 0, None),
 S(None, None, None, None, None), "desktop_pc", 3500,
 "Pushy, evasive; refuses viewing or pickup, insists on Swish upfront, pressures with 'många intresserade', disappears if asked for ID or meeting.", "sv", "scam",
 "Textbook Blocket scam: RTX 3080/i9 PC for a third of market price, 2-day-old account, Swish in advance, no viewing. True specs unknown (item doesn't exist).",
 ["price far below market", "new account", "swish/payment in advance", "refuses viewing", "urgency", "vague location"])

add(F, "RTX 4070 Gaming PC - Ryzen 7 7800X3D - 32GB - 2TB",
 "Hello, I am selling my gaming PC because I moved to Spain for work. RTX 4070, Ryzen 7 7800X3D, 32GB DDR5, 2TB NVMe. Like new. Price 4000 SEK. I can only ship with DHL, payment by bank transfer and you get tracking number. Serious buyers only.",
 4000, "Stockholm", True, 1, ("Jessica Brown", 5, 0, None),
 S(None, None, None, None, None), "desktop_pc", 4000,
 "Overly formal English, keeps repeating 'serious buyers only', insists on bank transfer to a foreign IBAN, sends fake DHL links.", "en", "scam",
 "Abroad-seller scam: seller 'in Spain', shipping only, bank transfer, absurd price for a 7800X3D/4070 build, brand-new account.",
 ["price far below market", "new account", "seller abroad", "shipping only", "bank transfer only", "generic English text"])

add(T, "Speldator RTX 3070 Ti 32GB 2TB NVMe Köp Nu",
 "Säljer speldator RTX 3070 Ti, Ryzen 7 5800X, 32GB RAM, 2TB NVMe. Fungerar perfekt. Endast frakt. Betalning sker via betalningslänk som jag skickar på mail, ej via Tradera.",
 4500, "Malmö", True, 0, ("tech_deals_2026", 4, 0, None),
 S(None, None, None, None, None), "desktop_pc", 4500,
 "Tries to move the conversation off-platform to email/WhatsApp, sends phishing 'payment links', vague about details.", "sv", "scam",
 "Off-platform payment link scam (phishing). Signals: new account, no reviews, payment outside the platform, shipping only.",
 ["price far below market", "new account", "off-platform payment link", "shipping only", "asks to move to email"])

add(F, "Hello dear buyer, gaming computer RTX 3090 for sale cheap",
 "Hello dear buyer, I am selling my gaming computer with RTX 3090 24GB graphics card, Intel Core i9, 64GB memory, 4TB SSD. Is in perfect condition and working 100%. Price is 3900kr because i need money urgent for my family. Please contact me on WhatsApp +44 7700 900123 for fast deal. God bless.",
 3900, "Stockholm", True, 0, ("Grace Williams", 1, 0, None),
 S(None, None, None, None, None), "desktop_pc", 3900,
 "Copy-paste broken English, sob story about family, pushes to WhatsApp with a UK number, asks for gift cards or Western Union.", "en", "scam",
 "Obvious copy-paste scam meant to be funny in the demo. Foreign phone number, WhatsApp, emotional urgency, absurd specs/price.",
 ["price far below market", "new account", "copy-paste English", "move to WhatsApp", "foreign phone number", "urgency", "sob story"])

add(B, "Speldator RTX 3060 Ti, Ryzen 5 5600X, 16 GB, 1 TB",
 "Hej! Säljer min speldator, rtx 3060 ti, r5 5600x, 16gb ram, 1tb nvme. Funkar perfekt, kan skicka bilder på benchmark. Många intresserade så först till kvarn. För att hålla den åt dig vill jag ha 1000 kr i handpenning via swish, resten vid leverans. Hämtning är tyvärr svårt just nu pga jobb men jag kan skicka med Postnord.",
 5200, "Kungsholmen, Stockholm", True, 1, ("Sofia Lind", 3, 0, None),
 S(None, None, None, None, None), "desktop_pc", 5200,
 "Friendly and fluent Swedish, sounds legit, but always has an excuse not to meet and keeps asking for the 'handpenning' deposit first.", "sv", "scam",
 "Subtle scam: specs match perfectly and price is only somewhat low, Swedish is natural. Signals are the deposit request, new account, and refusal of pickup despite Stockholm location. Hardest scam to catch.",
 ["new account", "deposit/handpenning in advance", "refuses pickup despite local location", "urgency", "price somewhat below market"])

# ---------------- REJECTS / NOISE ----------------
add(B, "Gaming laptop ASUS TUF RTX 3060 16gb 512gb",
 "ASUS TUF Gaming F15, RTX 3060 (laptop), i7-11800H, 16gb ram, 512gb ssd, 144hz skärm. Laddare medföljer. Lite slitage på tangenterna. Hämtas Sundbyberg eller skickas.",
 6500, "Sundbyberg, Stockholm", True, 5, ("Viktor N.", 1800, 13, 4.8),
 S("RTX 3060 Laptop GPU 6GB", "Core i7-11800H", 16, 512, "SSD"), "laptop", 5800,
 "Normal, helpful seller, open to small discounts.", "sv", "reject",
 "Laptop, not a desktop gaming PC; laptop 3060 is weaker and only 512 GB. Keyword 'RTX 3060 16gb' noise.")

add(T, "Grafikkort RTX 3060 12GB MSI Gaming X",
 "MSI RTX 3060 Gaming X 12GB. Använt ca 2 år, aldrig minat. Originalkartong finns. Skickas.",
 2300, "Västerås", True, 8, ("hw_flipper", 2700, 64, 4.9),
 S("RTX 3060 12GB", None, None, None, None), "gpu_only", 2100,
 "Professional hardware flipper, quick and businesslike, minimal haggling.", "sv", "reject",
 "GPU only, not a PC. Classic keyword false positive.")

add(F, "PS5 disc edition + 2 controllers",
 "PS5 disc version with 2 controllers and FIFA 25 + Spider-Man 2. Works perfectly. Pickup Farsta.",
 3500, "Farsta, Stockholm", False, 2, ("Leo S.", 1400, 9, 4.9),
 S(None, None, None, None, None), "console", 3200,
 "Friendly, relaxed English, fine with a small discount.", "en", "reject",
 "Console, matches 'gaming' keyword only.")

add(B, "Chassi NZXT H510 + nätagg 650w",
 "Säljer chassi NZXT H510 vit med glaspanel + Corsair 650w nätagg. Inga övriga delar. Perfekt till nytt bygge. Hämtas Hornstull.",
 600, "Södermalm, Stockholm", False, 12, ("Ida", 2000, 6, 5.0),
 S(None, None, None, None, None), "parts", 500,
 "Easygoing, will throw in some old case fans for free.", "sv", "reject",
 "Parts only. 'Speldator'-adjacent noise.")

add(B, "Speldator RTX 3070 startar inte - säljes som defekt",
 "Speldator rtx 3070, i7 9700k, 16gb, 1tb ssd. Startar inte, fläktarna snurrar en sekund sen dör den. Troligen nätagget eller moderkortet, vet ej. Säljes som den är, inga garantier. Hämtas Bromma.",
 3000, "Bromma, Stockholm", False, 3, ("Robin T.", 2300, 17, 4.6),
 S("RTX 3070", "Core i7-9700K", 16, 1000, "SSD"), "desktop_pc", 2500,
 "Honest about the defect, no-nonsense, won't guarantee anything.", "sv", "reject",
 "Broken PC with great specs ('startar inte'). Agent must read the description, not just the spec line.")

add(T, "Dell OptiPlex 7070 i5 16GB 256GB SSD - kontorsdator",
 "Dell OptiPlex 7070 SFF, Intel i5-9500, 16GB RAM, 256GB SSD, Windows 11 Pro. Integrerad grafik. Perfekt för kontor/hemmabruk. Klarar lättare spel.",
 1200, "Solna, Stockholm", True, 6, ("IT-Återbruk AB", 3500, 412, 4.9),
 S("Intel UHD 630 (integrated)", "Core i5-9500", 16, 256, "SSD"), "desktop_pc", 1100,
 "Company reseller, polite template replies, fixed prices with tiny volume discounts.", "sv", "reject",
 "Office PC with integrated graphics; '16GB' and 'klarar lättare spel' make it a keyword hit.")

add(F, "Gaming monitor 27\" 165Hz 1440p",
 "AOC 27\" 1440p 165Hz gaming monitor, great for RTX 3060/3070 setups. No dead pixels. Pickup Solna.",
 1500, "Solna, Stockholm", False, 4, ("Hannah B.", 1600, 8, 4.8),
 S(None, None, None, None, None), "other", 1300,
 "Friendly, happy to bundle with a desk if you want.", "en", "reject",
 "Monitor that mentions 'RTX 3060' in text - noise for keyword search.")

add(B, "KÖPES: Speldator RTX 3060 eller bättre",
 "Köper speldator med minst rtx 3060, 16gb ram och 1tb ssd. Betalar upp till 6000kr beroende på skick. Hämtar i Stockholm. Skicka pm!",
 6000, "Stockholm", False, 1, ("Andreas", 1100, 4, 4.8),
 S(None, None, None, None, None), "other", None,
 "Another buyer, not a seller; will reply asking what you're selling.", "sv", "reject",
 "'Köpes' (wanted) ad - matches all keywords perfectly but it's a buyer. Agent must not try to buy from it.")

# ---------------- EDGE CASES ----------------
add(B, "RTX 3070 / R7 5800X / 16GB / 1TB - billigt, hämtas endast",
 "Speldator rtx 3070, ryzen 7 5800x, 16gb 3600mhz, 1tb nvme, 750w. Toppskick. Billigt pga vill bli av med den snabbt. Hämtas endast i Västerås, skickar INTE. Inga undantag.",
 6500, "Västerås", False, 2, ("Mattias E.", 2800, 28, 4.9),
 S("RTX 3070", "Ryzen 7 5800X", 16, 1000, "SSD"), "desktop_pc", 6000,
 "Practical, friendly but absolutely refuses shipping; may agree to meet halfway (Enköping) if asked nicely.", "sv", "near_miss",
 "Great deal but in Västerås (~1.5-2h) with no shipping; violates 'pickup in Stockholm or shipping'. Agent should surface it as a tradeoff, not silently match or drop.")

add(T, "Speldator RTX 3060 - 16GB - 1TB SSD - i5",
 "Fin speldator med RTX 3060-klass grafik. Grafikkort: Nvidia RTX 3050 8GB (presterar nästan som 3060). Intel i5-10400F, 16GB RAM, 1TB SSD. Skickas med DHL.",
 6400, "Uppsala", True, 5, ("datorfixarn", 1300, 22, 4.3),
 S("RTX 3050 8GB", "Core i5-10400F", 16, 1000, "SSD"), "desktop_pc", 5700,
 "Slippery reseller who defends the misleading title ('det är samma klass'), gets defensive if called out but discounts when cornered.", "sv", "near_miss",
 "Lying title: says RTX 3060 but description reveals an RTX 3050. Tests reading description over title.")

add(F, "Gaming rig RTX 3060 16GB 1TB - barely used",
 "Barely used gaming rig, RTX 3060, 16GB RAM, 1TB SSD, i7-12650H, 144Hz 15.6\" display, RGB keyboard. MSI Katana GF66. Comes with charger. Pickup Kista or shipping.",
 7200, "Kista, Stockholm", True, 3, ("Chris L.", 900, 4, 4.5),
 S("RTX 3060 Laptop GPU 6GB", "Core i7-12650H", 16, 1000, "SSD"), "laptop", 6500,
 "Salesy, avoids the word 'laptop', but admits it if asked directly.", "en", "reject",
 "Sneaky: called a 'gaming rig' with 'RTX 3060' but it's an MSI Katana laptop (3060 Laptop GPU, 6 GB, notably weaker). Clues: H-series CPU, display, charger, model name.")

add(B, "Speldator RTX 3070 / Ryzen 7 5800X / 32GB / 2TB NVMe",
 "Säljer min välskötta speldator. RTX 3070 (ASUS Dual), ryzen 7 5800x, 32gb ddr4 3600 (4x8), 2tb nvme (1tb samsung 970 evo + 1tb crucial p5). Be quiet! Pure Base 500DX chassi. 750w gold. Kör allt i 1440p högt. Hämtas Enskede eller skickas. 8800kr, kan diskuteras lite.",
 8800, "Enskede, Stockholm", True, 4, ("Elin H.", 2500, 18, 4.9),
 S("RTX 3070", "Ryzen 7 5800X", 32, 2000, "SSD"), "desktop_pc", 8200,
 "Warm, reasonable Swedish seller who explains why it's worth the money, meets partway but won't go under 8200.", "sv", "match",
 "Best-spec match but slightly over budget even at the floor (min 8200). Agent should ask the user whether +200 kr is worth 32 GB/2 TB/3070.")

add(T, "RTX 3060 Ti Gaming PC Ryzen 5 5600 16GB 1TB - frakt 450kr",
 "Gaming PC RTX 3060 Ti, Ryzen 5 5600, 16GB DDR4, 1TB NVMe. Very good condition. Shipping from Malmö with DHL Freight (450 SEK, well packed). Swedish or English fine.",
 7700, "Malmö", True, 6, ("Nils Bergström", 3300, 58, 4.9),
 S("RTX 3060 Ti", "Ryzen 5 5600", 16, 1000, "SSD"), "desktop_pc", 7300,
 "Very trustworthy, established Tradera seller, polite bilingual, will cover half the shipping instead of lowering the price.", "en", "match",
 "Match, but total cost with shipping (7700+450) exceeds 8000. Tests landed-cost reasoning; negotiation can get it under budget.")

random.seed(42)
random.shuffle(L)
cnt = {}
pref = {B: "bl", T: "tr", F: "fb"}
out = []
for x in L:
    p = pref[x["source"]]; cnt[p] = cnt.get(p, 0) + 1
    out.append({"id": f"{p}-{cnt[p]:03d}", **x})
json.dump(out, open("/data/hack/haggle/data/listings.json", "w"), ensure_ascii=False, indent=2)
