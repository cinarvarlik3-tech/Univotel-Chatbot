-- Spec 020 Part C — district-neutral location re-anchors, neutral gender phrasing, base funnel copy.
-- Review Turkish with Çınar before applying to production.

-- C.1 District-neutral location re-anchor
UPDATE canned_responses SET content =
 'İstanbul''un pek çok yerinde şubemiz bulunuyor efendim. Üniversitenizi ve kız mı erkek öğrenci için mi baktığınızı söylerseniz size en uygun şubeyi iletebilirim.'
 WHERE short_code = 'div_location_new';

UPDATE canned_responses SET content =
 'İstanbul genelinde pek çok noktada şubemiz var efendim. Üniversitenizi ve kız mı erkek öğrenci için mi baktığınızı söylerseniz size en uygun konumu iletebilirim.'
 WHERE short_code = 'div_location_new_alt';

UPDATE canned_responses SET content =
 'İstanbul''un pek çok yerinde şubemiz bulunuyor efendim. Hangi üniversitede okuduğunuzu söylerseniz size en uygun şubeyi iletebilirim.'
 WHERE short_code = 'div_location_await_uni';

UPDATE canned_responses SET content =
 'İstanbul genelinde birçok şubemiz bulunuyor efendim. Hangi üniversite için baktığınızı söylerseniz size en uygun konumu iletebilirim.'
 WHERE short_code = 'div_location_await_uni_alt';

UPDATE canned_responses SET content =
 'İstanbul genelinde birçok şubemiz var efendim. Kız mı erkek öğrenci için mi baktığınızı söylerseniz size en uygun konumu iletebilirim.'
 WHERE short_code = 'div_location_await_gender';

UPDATE canned_responses SET content =
 'İstanbul''un pek çok yerinde hizmet veriyoruz efendim. Kız mı erkek öğrenci için mi aradığınızı söylerseniz size en uygun şubeyi iletebilirim.'
 WHERE short_code = 'div_location_await_gender_alt';

-- C.2 Gender-neutral await_gender divergence messages
UPDATE canned_responses SET content =
 'Efendim kız ve erkek öğrencilerimiz için ayrı şubelerimiz bulunuyor. Hangisi için baktığınızı söylerseniz size uygun fiyatı iletebilirim.'
 WHERE short_code = 'div_price_await_gender';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimiz için ayrı şubelerimizde fiyatlandırma yapıyoruz efendim. Hangisi için baktığınızı söylerseniz iletebilirim.'
 WHERE short_code = 'div_price_await_gender_alt';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimize ayrı şubelerimizde hizmet veriyoruz efendim. Hangisi için baktığınızı söylerseniz doluluk durumunu iletebilirim.'
 WHERE short_code = 'div_vacancy_await_gender';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimiz için ayrı şubelerimizde müsaitlik takip ediyoruz efendim. Hangisi için baktığınızı söylerseniz kontrol edip iletebilirim.'
 WHERE short_code = 'div_vacancy_await_gender_alt';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimiz için ayrı şubelerimiz var efendim. Hangisi için baktığınızı söylerseniz ödeme detaylarını iletebilirim.'
 WHERE short_code = 'div_payment_await_gender';

UPDATE canned_responses SET content =
 'Ödeme koşullarını kız ve erkek şubelerimiz için ayrı ayrı iletiyoruz efendim. Hangisi için baktığınızı söylerseniz paylaşabilirim.'
 WHERE short_code = 'div_payment_await_gender_alt';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimiz için ayrı şubelerimiz bulunuyor efendim. Hangisi için baktığınızı söylerseniz size uygun konaklamayı önerebilirim.'
 WHERE short_code = 'div_housing_await_gender';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimize ayrı şubelerimizde hizmet veriyoruz efendim. Hangisi için baktığınızı söylerseniz yardımcı olabilirim.'
 WHERE short_code = 'div_housing_await_gender_alt';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimiz için ayrı şubelerimiz var efendim. Öğrencimiz hangisi için bakıyorsunuz?'
 WHERE short_code = 'div_parent_await_gender';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimize ayrı şubelerimizde hizmet veriyoruz efendim. Öğrencimiz için hangisine baktığınızı söylerseniz devam edebilirim.'
 WHERE short_code = 'div_parent_await_gender_alt';

UPDATE canned_responses SET content =
 'Evet efendim, İstanbul genelinde hizmet veriyoruz. Kız ve erkek öğrencilerimiz için ayrı şubelerimiz var; hangisi için baktığınızı söylerseniz devam edebilirim.'
 WHERE short_code = 'div_coverage_await_gender';

UPDATE canned_responses SET content =
 'İstanbul genelinde hizmet veriyoruz efendim. Kız mı erkek öğrenci için mi baktığınızı söylerseniz size uygun şubeyi önerebilirim.'
 WHERE short_code = 'div_coverage_await_gender_alt';

UPDATE canned_responses SET content =
 'Kız ve erkek öğrencilerimiz için ayrı şubelerimizde farklı koşullar olabiliyor efendim. Hangisi için baktığınızı söylerseniz iletebilirim.'
 WHERE short_code = 'div_eligibility_await_gender';

UPDATE canned_responses SET content =
 'Kimlerin kalabileceğine dair bilgiyi kız ve erkek şubelerimiz için ayrı ayrı iletiyoruz efendim. Hangisi için baktığınızı söylerseniz paylaşabilirim.'
 WHERE short_code = 'div_eligibility_await_gender_alt';

-- C.3 Base-flow gender ask
UPDATE canned_responses SET content =
 'Efendim öğrencimizin kız mı erkek mi olduğunu öğrenebilir miyim? Ona göre size en uygun şubemizi önerebilirim.'
 WHERE short_code = 'kiz-erkek';
