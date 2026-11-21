# Missing dog photos: independently verified external photo leads — 21 November 2026

This is a read-only recovery record for the 48 lost October/November 2026 uploads across 19 published dogs, previously inventoried in [MISSING_DOG_PHOTO_RECOVERY_2026-11-20.md](MISSING_DOG_PHOTO_RECOVERY_2026-11-20.md).

**Original bytes recovered: 0 of 48.** SHA-256 matching was completed for 114 downloaded image URLs from 11 independent breeder/pedigree pages, against all 47 available original fingerprints. No matches. One lost original (Sforza Neron IMG_0347.jpeg) has no known SHA256, so it requires manual provenance confirmation. Of the 114 candidates, only three downloads had explicit alt-text naming the affected dog. The three additional pedigree thumbnails below were on the specific named-dog profiles. All are **alternative image candidates**, not recovered originals. Do **not** overwrite missing original keys or republish a photo before identity, reuse rights and breeder consent are checked.

## Downloadable, tested same-dog image leads

| Affected dog | Source and verified photo URL | Download SHA-256 | Interpretation |
| --- | --- | --- | --- |
| Kralj Custodi Nos | [Cape Fear photo](https://static.wixstatic.com/media/638a53_b3dc7f99df6a4d06beabcf5c8dddf8d0~mv2.jpg) ([breeder page](https://www.capefearcanecorso.com/single-post/karlj-custodi-nos)) | `094b9a315a504ae7c85ad2230318a3d5c25b156ca64404cde9bf0214b546f4e7` | Dog explicitly named; not either lost upload |
| Ultimo Vidor Custodi Nos | [Pienluti Del Corso photo](https://netkennel.sistemapet.com.br/202532/psb_252015_20250810153003.webp?t=1763673118) ([breeder page](https://pienlutidelcorso.com.br/filhote/Cane-Corso/22225)) | `d1e71ed31fb2f15b4132362bad5b4439937cf09d8f0e9cc5a2b298a36cc85b7c` | Dog explicitly named; not one of three missing uploads |
| Sforza Deja Vue | [Del Estancio photo](https://delestanciokennel.com/__l5e/assets-v1/63e70582-eb21-4f3d-921a-3944e56b4ff4/Sforza_Deja_Vue_1.jpg) ([breeder site](https://delestanciokennel.com/en)) | `581f545db0cdf969fbfee3eac95f3bee1161274a492a75a6286e59da957e9495` | Dog explicitly named; not one of two missing uploads |
| Oragorn Custodi Nos | [Pedigree profile photograph](https://canecorsopedigree.com/static/images/animal/thumbnails/img69e0vrh7xgi3.jpg_400.jpeg) ([dog profile](https://canecorsopedigree.com/view_dog?id=120615)) | `f2f29e31fc7fe5653c72c703f1f10958d0db745a4ee9bc5e56859da3cb3e234d` | Matching named dog's profile; not one of five missing uploads |
| Don Simba | [Pedigree profile photograph](https://canecorsopedigree.com/static/images/animal/thumbnails/imgs1r2bawqi7mz.jpg_400.jpeg) ([dog profile](https://canecorsopedigree.com/view_dog?id=119534)) | `a6eac8c5ecea627300998c7955a11bc0607f24f5e32186476778fbad91a1649e` | Matching named dog's profile; not one of two missing uploads |
| Capri Linea Rossa | [Pedigree profile photograph](https://canecorsopedigree.com/static/images/animal/thumbnails/img3bropv7cmegz.jpg_400.jpeg) ([dog profile](https://canecorsopedigree.com/view_dog?id=118503)) | `2526cbc5c969e8d0c9fe892ef3c54251381b5e3e5277f09630415958787e70d7` | Matching named dog's profile; not any of four missing uploads |

## Additional breeder/owner source pages

- **B-Aquila Clarissima Stella** — [I Molossi Del Porto stud profile](https://www.imolossidelporto.co.uk/studs/) with dog photo and health-test tiles; [Pets4Homes advert](https://www.pets4homes.co.uk/classifieds/y-xjfyemz-health-tested-fci-registered-gosport/). The scan found image URLs but their image tags lacked exact-name alt descriptions, so none was certified as a missing upload.
- **Kralj Custodi Nos** — [Cape Fear dedicated gallery](https://www.capefearcanecorso.com/single-post/karlj-custodi-nos) includes multiple images; not all images on the page show Kralj. Do not bulk import.
- **Sforza Deja Vue** — Del Estancio displays the named dog in its female collection; first image verified above. The site's text advertises two images but the scan only isolated one direct URL.
- **Oragorn Custodi Nos** — an older named image is also present in Google Drive as `120615_ORAGORN_CUSTODI_NOS.jpg` (Drive ID `16wYHDtWijPDG7oeTfIyAfqsIFvrB8ZOQ`), separate from the new missing uploads.
- **Tabasco En Una Palabra** — an older named image is in Google Drive as `88648_TABASCO_EN_UNA_PALABRA.jpg` (Drive ID `1hyuLSv3MLXIRLXcrFijQ_U-OCCkQnfIJ`), and already serves as a pre-approved same-dog fallback for the missing `IMG_1946.jpg`. It is not the missing original.
- **Don Simba and Capri Linea Rossa** — older same-dog Drive photos remain available (IDs `1a0O3TZWreG3pcxWY8ynCd328CUGsHQWf` and `1DCmjUdATy-OQ7KBUbxsK2Sq17h6Fj-kP`), already accounted for in the existing inventory.

## Investigation audit

- [Wayback + Common Crawl probe](https://github.com/eghosa001/canecorsoancestry/actions/runs/44921498925): 0 archived URLs located; Common Crawl queries had API errors, so do not claim that corpus was conclusively checked.
- [Signed Cloudflare media probe](https://github.com/eghosa001/canecorsoancestry/actions/runs/44921970071): 140 requests; 137 HTTP 500, three distinct URL variants returning the same pre-existing Tabasco Drive fallback; no originals.
- [Breeder/gallery hash comparison](https://github.com/eghosa001/canecorsoancestry/actions/runs/44922923847): 11 source pages; 114 unique downloadable images; 0 SHA-256 matches. See `cca-breeder-photo-candidates-hash-checked` artifact for source URLs, HTTP failures and sha hashes.

## Practical next recovery paths

1. Recover **originals** via temporarily restoring Cloudflare R2 read access and using `recover_r2_media_to_oracle`, which never deletes source objects. Do not clear or replace the old bucket.
2. Search the original uploader's iPhone Photos, Google Photos, WhatsApp chats, iCloud, and synced albums using **October/November 2026** creation dates; compare SHA-256 to originals before marking recovered.
3. With explicit breeder/owner consent, use the same-dog external photos above as separately sourced alternatives. Never falsely mark a resized or third-party image as one of the exact 48 restored originals.

No production DogImage rows, old missing-key mappings, consent flags, billing settings or media files were changed by this investigation.
