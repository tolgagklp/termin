# Ehliyet: yabancı ehliyetin dönüştürülmesi

**Hizmet:** [Umschreibung eines ausländischen Führerscheins](https://stadt.muenchen.de/service/info/fuhrerscheinstelle/1071898/) · **Randevu:** [KVR Terminvereinbarung](https://stadt.muenchen.de/buergerservice/terminvereinbarung.html) · **Saat dilimi:** Münih (Europe/Berlin).

| Ne zaman yeni randevu açılıyor? | Gün | Münih saati | KVR'nin açıklaması |
| --- | --- | --- | --- |
| Aynı gün için | Pazartesi–Cuma | **07:00–08:00** | Kapasiteye göre o güne ait boş saatler açılıyor; her gün boş saat garantisi yok. |
| 14 gün önceden | Pazartesi–Cuma | **07:30–08:30** | 14 gün ileri tarihli randevular açılıyor. |

Bu saatler, randevu ekranındaki **“Wann gibt es neue Termine?”** açıklamasından (20.10.2026 tarihli ekran görüntüm) alınmıştır. İki aralık **07:30–08:00** arasında çakışır; boş saatler sonradan da kaybolup geri gelebilir.

| Konu | Kısa bilgi |
| --- | --- |
| Resmî başvuru zamanı | KVR'ye göre yabancı ehliyetle Almanya'daki ilk kayıttan sonra **6 ay** araç kullanılabilir; ardından dönüştürülmesi gerekir. Bu süre dolmadan başvuruyu planlamalıyım. EU/EWR ehliyetleri için ayrı kurallar vardır. [Kaynak](https://stadt.muenchen.de/service/info/fuhrerscheinstelle/1071898/). |
| Yer ve işlem | **Führerscheinstelle, Garmischer Straße 19–21.** Randevu sayfasında “Umschreibung eines ausländischen Führerscheins” seçilir. |
| Belgeler ve işlem süresi | Belgeleri [resmî listeden](https://stadt.muenchen.de/service/info/fuhrerscheinstelle/1071898/) kontrol etmeliyim. KVR, eksiksiz belgelerden sonra işlem süresini **14 haftaya kadar** bildiriyor. |
| Benim tarih tercihim | **30 Ekim 2026'ya kadar:** herhangi bir saat. **2–20 Kasım:** erken sabah veya geç saat. **Son sınır: 24 Kasım 2026.** Bunlar KVR kuralı değil, benim tercihlerim. |
| Benim gözlemim | **3 Kasım 2026** için birden çok öğleden sonra saati gördüm; sonra boş saat kalmadı. Başka bir taramada yalnız **15:40** göründü. Görünen kontenjan hızla değişiyor. |
| Rezervasyon akışı | Uygun gün/saat → iletişim bilgileri → özet ekranında **elektronik haberleşme onayı** → “Termin reservieren”. Gelen e-postadaki bağlantıyı **ben** etkinleştiririm. |
| Botun şu anki durumu | Ehliyet botu uygun saatleri izliyor ve bildiriyor. `.env` içindeki `AUTO_BOOK_ENABLED=false` olduğu sürece rezervasyon göndermiyor. |

| Yerel komutlar — proje klasöründe PowerShell | Komut |
| --- | --- |
| İzlemeyi başlat | `.\.venv\Scripts\python.exe -m src.driver_license_monitor` |
| Son durumu gör | `.\.venv\Scripts\python.exe -m src.driver_license_monitor --status` |
| Günlüğü canlı izle | `Get-Content .\monitor\monitor.log -Wait -Tail 30` |

# Blue Card: öğrenci/mezun Notfall randevusu

**Hizmet:** [Notfall-Hilfe Aufenthaltstitel – Studierende, Arbeitsplatzsuche nach Studium oder erstmalige Beschäftigung nach Studium](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10338844/) · **Randevu:** [KVR Terminvereinbarung](https://stadt.muenchen.de/buergerservice/terminvereinbarung.html) · **Saat dilimi:** Münih (Europe/Berlin).

| Gün | Hatırlatma | Resmî açılış | Hangi randevu? |
| --- | --- | --- | --- |
| Pazartesi, çarşamba, cuma | **06:20** | **06:30** | Yalnızca **o gün** için. |
| Salı, perşembe | **07:20** | **07:30** | Yalnızca **o gün** için. |
| Hafta sonu | — | — | Bu kategori için açıklanmış açılış saati yok. |

KVR'nin [hizmet sayfası](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10338844/) ve randevu ekranındaki **“Wann gibt es neue Termine?”** açıklaması bu saatleri veriyor. Randevu ücretsiz; ücretli üçüncü taraf tekliflerini kullanmamalıyım.

| Konu | Kısa bilgi |
| --- | --- |
| Bana uygun kategori | Hâlen öğrenci olduğum için **öğrenci/mezun Notfall** hizmetini seçiyorum; “Beschäftigte, Angehörige” farklı kategoridir. |
| Acil durum şartı | Yalnızca **belgelenebilir acil durumlar** inceleniyor. İş veya iş teklifi kaybı tehlikesi örneklerden biri; acil olup olmadığına KVR karar veriyor. [Öğrenci hizmeti](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10338844/). |
| İşe başlama ve Blue Card | Yalnızca işe başlamak acil durum sayılmıyor. Notfall gişesi Blue Card verme/uzatma işlemini yapmıyor. [Blue Card başvurusu](https://stadt.muenchen.de/service/en-GB/info/servicestelle-fur-zuwanderung-und-einburgerung/10422541/) ayrı olarak çevrim içi veya postayla yapılır; incelemeden sonra KVR görüşme randevusu verir. [Genel Notfall açıklaması](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10339065/). |
| Benim gözlemim | **20 Ekim 2026:** İnsan doğrulamasını elle tamamlayınca tarih ekranı açıldı; **boş randevu yoktu**. Sayfa yenilenince doğrulama yeniden istendi. |
| Telegram ne yapıyor? | **Aynı bot**, resmî açılıştan 10 dakika önce ve açılışta bağlantılı hatırlatma gönderiyor. **Boş saatleri kontrol etmiyor, rezervasyon yapmıyor.** Gönderim kaydı tekrar mesajı önlüyor. |
| Boş randevu bulamazsam | KVR servis telefonu: **+49 89 233-96010**. [Kaynak](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10338844/). |

| Yerel komutlar — proje klasöründe PowerShell | Komut |
| --- | --- |
| Hatırlatıcıyı başlat | `.\.venv\Scripts\python.exe -m src.notfall_reminder` |
| Gelecek saatleri gör | `.\.venv\Scripts\python.exe -m src.notfall_reminder --status` |
| Günlüğü canlı izle | `Get-Content .\monitor\notfall\reminder.log -Wait -Tail 30` |

İki program ayrı pencerelerde birlikte çalışabilir; pencereleri **Ctrl+C** ile durdurabilirim. Bilgisayarın uyanık ve internete bağlı olması gerekir. Notfall kayıtları `monitor/notfall/` içindedir; bu klasör ve gizli `.env` Git'e eklenmez. Notfall için ayrı bitiş tarihi gerekiyorsa `.env` içine `NOTFALL_REMINDER_UNTIL=YYYY-MM-DD` yazabilirim.
