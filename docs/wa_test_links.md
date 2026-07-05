# Univotel Chatbot — Functional Test Message Links (F1–F10)

All links direct to the Univotel WhatsApp number (`0212 909 52 44` → `902129095244`).
Click each link in order within a test; the message opens prefilled in WhatsApp — hit send.
**Run the teardown SQL between tests** (reset conversation state) or state bleeds over.

```sql
-- TEARDOWN between every test (replace 52 with the test conversation cw_id):
UPDATE conversations SET flow_state=NULL, university_id=NULL, gender=NULL,
  pending_parent_university_id=NULL, ilgili_otel=NULL, ilgili_otel_set_at=NULL,
  ilgili_otel_set_by=NULL, auto_run_count=0, manual_run_count=0 WHERE cw_id=52;
```

## F1 — Parent-escalating diacritic (Boğaziçi) — must escalate

//F1 is successful except for 1 thing, InfoGatherer's phrase gate is too strict. It couldn't flag 'merhabalar üniversiteme yakın konaklama arıyorum' as a legitimate sentence to respond to. The phrase gate needs work. 
//Probably because it looks for "Başvuru Kodu" to guarantee that this is an inquiry about a hotel. Smart for V0 but not scalable. 
//Could insert FallBack layer here or could extend the phrase gate. 

1. **`Merhabalar, üniversiteme yakın konaklama arıyorum`**
   https://wa.me/902129095244?text=Merhabalar%2C%20%C3%BCniversiteme%20yak%C4%B1n%20konaklama%20ar%C4%B1yorum

   //Failed due to phrase gate of InfoGatherer 
   //INFO:     34.40.45.231:0 - "POST /webhooks/chatwoot HTTP/1.1" 200 OK
   2026-07-04 20:41:29,226 INFO app.layers.info_gatherer InfoGatherer: phrase gate failed for conversation a1651d59-db6e-4611-ae26-3438256cfee4
   //Proceeding to step 2 with a phrase that has been proven to work.

2. **`boğaziçi`**
   https://wa.me/902129095244?text=bo%C4%9Fazi%C3%A7i

   //Input received just fine.
   //Parent university escalation succeeded. 
   SUCCESS STEP

3. **`Ana Kampüs`**
   https://wa.me/902129095244?text=Ana%20Kamp%C3%BCs

   //Input received just fine.
   //Proceeded to ask for gender.
   //When gender is provided, returned the correct result from RecEngine. 
   SUCCESS STEP


*(run teardown after this test)*

## F2 — ASCII variant (bogazici) — identical escalation to F1

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba

   //Phrase gate failed for 'merhaba'. 
   //InfoGatherer's phrase gate needs to be expanded with more if-then scenarios. It should be able to recognize and return simple greetings, subtle inquiries etc.
   //Proceeding to step 2 with a guaranteed text. 

2. **`bogazici`**
   https://wa.me/902129095244?text=bogazici

   //Input received successfully
   //bogazici mapped to Boğaziçi successfully
   SUCCESS STEP

*(run teardown after this test)*

## F3 — Üsküdar — 3-campus escalation, mixed suffixes

1. **`Merhabalar konaklama için yazıyorum`**
   https://wa.me/902129095244?text=Merhabalar%20konaklama%20i%C3%A7in%20yaz%C4%B1yorum

   //Phrase gate
   //Proceeding to 2 with guaranteed script

2. **`üsküdar`**
   https://wa.me/902129095244?text=%C3%BCsk%C3%BCdar

   //Input received successfully
   //Parent escalation successfull
   //Mixed suffixes successfull
   SUCCESS STEP

3. **`Merkez`**
   https://wa.me/902129095244?text=Merkez

   //RecEngine success according to rules
   //hotel_accessible_universities needs shrinking 
   //maybe priorityScore can be divided into districts
   //maybe some more absolute rules can be added like "school an dorm must be on the same continent". 
   SUCCESS STEP - Needs product design choices

*(run teardown after this test)*

## F4 — Doğuş — rounded-vowel suffixes mu/mü

1. **`selam`**
   https://wa.me/902129095244?text=selam

   //phrase gate
   //Proceeding to step 2 with guaranteed message

2. **`doğuş`**
   https://wa.me/902129095244?text=do%C4%9Fu%C5%9F

   //Input success
   //Parent escalation success
   //Suffixes success
   SUCCESS STEP

*(run teardown after this test)*

## F5 — Abbreviation SU (Sabancı) — single-campus, NO escalation

1. **`Merhaba, yurt arıyorum`**
   https://wa.me/902129095244?text=Merhaba%2C%20yurt%20ar%C4%B1yorum

   //Phrase gate
   //Proceeding with guaranteed text

2. **`su`**
   https://wa.me/902129095244?text=su

   //Short name to university attribution success
   //Single campus parent, no escalation success
   SUCCESS STEP

*(run teardown after this test)*

## F5b — Abbreviation KU (Koç) — direct

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba

   //Phrase gate, alt proceed

2. **`ku`**
   https://wa.me/902129095244?text=ku

   //Short name to university attribution success
   //Single campus parent, no escalation success

*(run teardown after this test)*

## F5c — Abbreviation GSÜ (Galatasaray) — direct

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba
2. **`gsü`**
   https://wa.me/902129095244?text=gs%C3%BC

*(run teardown after this test)*

## F5d — Abbreviation FBÜ (Fenerbahçe) — direct

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba
2. **`fbü`**
   https://wa.me/902129095244?text=fb%C3%BC

*(run teardown after this test)*

## F5e — Abbreviation ACU (Acıbadem) — direct

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba
2. **`acu`**
   https://wa.me/902129095244?text=acu

*(run teardown after this test)*

## F5f — Abbreviation PRÜ (Piri Reis) — direct

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba
2. **`prü`**
   https://wa.me/902129095244?text=pr%C3%BC

*(run teardown after this test)*

## F6 — Direct campus alias (taşkışla → İTÜ Maçka) — NO escalation

1. **`Merhabalar konaklama bilgisi alabilir miyim`**
   https://wa.me/902129095244?text=Merhabalar%20konaklama%20bilgisi%20alabilir%20miyim

   //Phrase gate alt procedure

2. **`taşkışla`**
   https://wa.me/902129095244?text=ta%C5%9Fk%C4%B1%C5%9Fla

   //taşkışla to İTÜ Maçka direct mapping FAILED
   //Escalation to ask again FAILED
   FAILED STEP

*(run teardown after this test)*

## F7 — ★ CROSS-PARENT COLLISION (Beykent → Ayazağa, must NOT be İTÜ) ★

1. **`Merhaba, üniversiteme yakın yer arıyorum`**
   https://wa.me/902129095244?text=Merhaba%2C%20%C3%BCniversiteme%20yak%C4%B1n%20yer%20ar%C4%B1yorum

   //Phrase gate alt reply

2. **`beykent`**
   https://wa.me/902129095244?text=beykent

   //Input success
   //Parent escalation success

3. **`Ayazağa`**
   https://wa.me/902129095244?text=Ayaza%C4%9Fa

   //Attribution to Beykent Ayazağa (NOT İTÜ) success
   SUCCESS STEP

*(run teardown after this test)*

## F8 — Invalid campus reply (İTÜ then 'Beşiktaş' — not a campus)

//Needs a reply for invalid campus name and invalid school name.

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba

   //Phrase gate, alt procedure

2. **`itü`**
   https://wa.me/902129095244?text=it%C3%BC

   //Already succeeds, nothing new; success

3. **`Beşiktaş`**
   https://wa.me/902129095244?text=Be%C5%9Fikta%C5%9F

   //No path for invalid campus name, just freezes. FAIL
   FAILED STEP

*(run teardown after this test)*

## F9 — Multi-word alias (kadir has)

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba

   //Phrase gate alt procedure

2. **`kadir has`**
   https://wa.me/902129095244?text=kadir%20has
   
   //2 word alias to university attribution success
   SUCCESS STEP

*(run teardown after this test)*

## F9b — Multi-word alias (ibn haldun)

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba
2. **`ibn haldun`**
   https://wa.me/902129095244?text=ibn%20haldun

*(run teardown after this test)*

## F9c — Multi-word alias (29 mayıs)

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba
2. **`29 mayıs`**
   https://wa.me/902129095244?text=29%20may%C4%B1s

*(run teardown after this test)*

## F10 — Negative — unrecognized university

1. **`merhaba`**
   https://wa.me/902129095244?text=merhaba

   //Phrase gate alt procedure

2. **`qwerty üniversitesi`**
   https://wa.me/902129095244?text=qwerty%20%C3%BCniversitesi

   //Returned out of city protocol, correct within the rules I defined.
   SUCCESS STEP -- But needs a product design choice: Are out of istanbul universities any different than made up universities? If they are, how can we separate them? Do we keep a list of all the universities in the country? I'd say it's fine as is, any university not in our list is safe to assume out of istanbul even if some are made up; there's no better response. Safer than risking treating a real school as if it was fake. 

*(run teardown after this test)*
