# OLE-Analyse: Robustheit, Performance und Writer-Korrektheit

Stand: extract_msg 0.55.0, `olefile==0.47` (gepinnt in `requirements.txt:5`).

Diese Notiz ist eine reine Bestandsaufnahme — es wurde **kein Produktivcode geändert**.
Untersucht wurde die Nahtstelle zwischen `extract_msg` und `olefile`: das Lesen jeder
`.msg`-Datei läuft durch `olefile`, das Schreiben durch die projekteigene
CFB-Implementierung in `extract_msg/ole_writer.py`.

Befunde mit ✅ wurden nicht nur gelesen, sondern nachgestellt bzw. nachsimuliert — teils
per Simulation der Arithmetik, teils gegen ein installiertes `olefile` 0.47. Das Skript zu
Befund A liegt unter `helper-scripts/difat_check.py`.

Einschränkung: die Testsuite (`python3 tests.py`) konnte in der Analyseumgebung nicht
ausgeführt werden, weil sich `red-black-tree-mod` dort nicht bauen lässt. Die Aussagen zur
Testabdeckung stützen sich daher auf die Inhalte von `extract_msg_tests/` und
`example-msg-files/`, nicht auf einen Lauf.

---

## Ausgangslage

- `MSGFile` erbt nicht von `OleFileIO`, sondern kapselt eine Instanz
  (`extract_msg/msg_classes/msg.py:57`, Konstruktion in `msg.py:155`). Eingebettete MSGs
  teilen sich das Handle des Parents (`msg.py:141`); nur der Owner schließt (`msg.py:423`).
- `olefile` wird ausschließlich mit `raise_defects` parametrisiert — kein `path_encoding`,
  kein `write_mode`. Der Default ist `DEFECT_INCORRECT`, also strenger als `olefile`s
  eigener Default. Die Namenslogik ist dabei invertiert:
  `ErrorBehavior.OLE_DEFECT_INCORRECT` *lockert* auf `DEFECT_FATAL`
  (`msg.py:151-155`, `extract_msg/enums.py:677`).
- Größte Beispieldatei im Repo: `example-msg-files/unicode.msg` mit 2 MB. Es gibt keine
  Fixtures für defekte oder abgeschnittene Dateien.

---

## A. Kritisch: DIFAT-Korruption im Writer ✅

`extract_msg/ole_writer.py:538-541`, beim Auffüllen des letzten DIFAT-Sektors:

```python
if numFat > 109:
    f.write(b'\xFF\xFF\xFF\xFF' * ((self.__linksPerSector - 1) - ((numFat - 109) % (self.__linksPerSector - 1))))
    f.write(b'\xFE\xFF\xFF\xFF')
```

Ist `(numFat - 109) % 127 == 0`, ergibt der Modulo `0`. Der Code schreibt dann `127 - 0`
= 127 FREESECT-Einträge **plus** den ENDOFCHAIN-Marker, obwohl im DIFAT-Sektor exakt
**null** Slots frei sind. Das sind 128 überzählige Einträge = **508 Byte Overflow** über
die deklarierte DIFAT-Region hinaus. Dadurch verschieben sich FAT und sämtliche
Folgesektoren; die erzeugte Datei lässt sich nicht mehr öffnen.

`helper-scripts/difat_check.py` vergleicht die emittierte Eintragszahl mit der im Header
deklarierten Kapazität (`109 + numDifat * 128`):

```
Checked sector counts 1..59999.
Mismatches: 254
FAT sector counts affected: [236, 363]
First failure: numberOfSectors=29845, numFat=236, numDifat=1, emitted=364 entries,
               expected=237 entries, overflow=508 bytes
Affected output sizes:
  sectors 29845-29971 => 14.57 MB - 14.63 MB
  sectors 45973-46099 => 22.45 MB - 22.51 MB
```

| | |
|---|---|
| Betroffene `numFat` | 236, 363, 490, … (`numFat ≡ 109 mod 127`, `numFat > 109`) |
| Erste Fehlerzone | 14,57 MB – 14,63 MB |
| Periode | 16 128 Sektoren ≈ 7,88 MB |
| Fensterbreite | 127 Sektoren ≈ 65 KB |
| Trefferquote | ≈ 0,8 % aller Ausgabegrößen oberhalb 14,5 MB |

Für MSG-Dateien mit großen Anhängen ist das realistisch erreichbar. Die Export-Tests in
`extract_msg_tests/ole_writer_tests.py` vergleichen byte-genau gegen Golden Files, die
alle unter 2 MB liegen — dieser Pfad wird also nie ausgeführt.

**Vorschlag:** Rest `0` als „Sektor voll" behandeln, etwa
`rest = (numFat - 109) % 127; fill = (127 - rest) if rest else 0`, und den ENDOFCHAIN nur
schreiben, wenn tatsächlich ein Slot frei bleibt. Sauberer wäre, die letzte Position jedes
DIFAT-Sektors grundsätzlich als Next-Pointer zu reservieren.

Der Rest der Sektor-Arithmetik ist solide: der Fixpunkt in `_getFatSectors`
(`ole_writer.py:351-366`) konvergiert korrekt, ebenso die DIFSECT/FATSECT-Markierung
(`ole_writer.py:549-551`) und der Next-DIFAT-Sprung (`ole_writer.py:531-533`).

---

## B. Robustheit beim Lesen

### B1. Fehlerübersetzung per String-Vergleich

`msg.py:156-161` fängt `OSError` und unterscheidet über
`if str(e) == 'not an OLE2 structured storage file'`. `olefile` 0.47 wirft an dieser
Stelle in Wahrheit `NotOleFileError` (Subklasse von `OleFileError`, die wiederum von
`OSError` erbt) — die Klasse wird im gesamten Repo nicht verwendet. Jeder andere
`olefile`-Fehler (`'incomplete OLE sector'`, `'incorrect OLE FAT, sector index out of
range'`, `'Stream referenced twice'`, …) propagiert unverändert nach außen. Dasselbe
Muster nochmal in `ole_writer.py:855-860` und `ole_writer.py:899-907`
(`str(e) == 'file not found'`).

Ein String-Vergleich ist an dieser Stelle brüchig, aber der naheliegende Fix ist nicht
gratis: ✅ `NotOleFileError` und `OleFileError` stehen in 0.47 **nicht** in
`olefile.__all__` und sind deshalb über `olefile.NotOleFileError` gar nicht erreichbar
(`AttributeError`). Sie liegen nur im Submodul `olefile.olefile`.

**Vorschlag:** entweder gezielt aus `olefile.olefile` importieren (mit Fallback auf
`OSError`, falls ein künftiges Release das umbaut) oder die Typprüfung defensiv über
`type(e).__name__` machen. In beiden Fällen sollte das Ergebnis hinter einem eigenen
`OleParsingError` gekapselt werden, damit Aufrufer nicht gegen `olefile`-Interna
programmieren müssen. Ein Upstream-Patch, der die beiden Klassen exportiert, wäre die
sauberste Lösung.

### B2. `parsing_issues` wird verworfen

`olefile` sammelt alle nicht-fatalen Defekte in `ole.parsing_issues` (siehe `_raise_defect`).
Im Repo gibt es keinen einzigen Zugriff darauf. Die Bibliothek kann damit nicht melden
„geöffnet, aber mit Problemen" — genau die Information, die bei Forensik oder
Bulk-Extraktion gebraucht wird.

**Vorschlag:** als `MSGFile.oleParsingIssues` durchreichen und bei nicht-leerer Liste
einmalig eine Warnung loggen.

### B3. Keine Absicherung um Stream-Reads

`getStream` (`msg.py:711-717`) hat kein `try`. Ein abgeschnittener Stream löst erst beim
Zugriff auf eine unscheinbare Property (`msg.subject`) einen `OSError` aus — potenziell
lange nach dem Öffnen und mitten in `saveRaw`/`export`.

Verschärfend kommt hinzu, dass `olefile.exists()` intern **alle** Exceptions schluckt
(`except Exception: return False`). Ein korrupter Directory-Eintrag wird dadurch still zu
„Stream nicht gefunden", `getStream` liefert `None`, und die Daten fehlen kommentarlos.
Das ist der unangenehmste Fall: Datenverlust ohne Fehlermeldung.

### B4. Zugriff auf `olefile`-Interna

`msg.py:271` und `msg.py:275` nutzen `self.__ole._find(...)` sowie
`self.__ole.direntries[sid]` ohne Guard. `_find` wirft `OSError('file not found')`, was bis
`AttachmentBase.clsid` (`extract_msg/attachments/attachment_base.py:523`) und
`OleWriter.fromMsg` (`ole_writer.py:818`) durchschlägt. Beim nächsten `olefile`-Upgrade
bricht das ohne Vorwarnung — was den harten Pin auf 0.47 miterklärt.

### B5. Keine Fixtures für defekte Dateien

`extract_msg_tests/` enthält keine korrupten oder abgeschnittenen MSGs. Sämtliche oben
genannten Pfade sind ungetestet.

---

## C. Performance beim Lesen

### C1. `listDir`-Cache greift bei Top-Level-Dateien nie ✅

`msg.py:789-805`:

```python
except KeyError:
    entries = self.__ole.listdir(streams, storages)
    if not self.__prefix:
        return entries          # Early Return - wird nie gecacht
```

Bei einer normalen, nicht eingebetteten MSG-Datei ist `__prefix == ''`, der Cache wird also
vollständig umgangen. Jeder `listDir`/`slistDir`-Aufruf lässt `olefile` den kompletten
Directory-Baum neu durchlaufen (`OleFileIO._list`, rekursiv über alle Kinder).

Teuer wird das, weil `_getTypedStream` (`msg.py:373`) bei unbekanntem Typ über
`self.slistDir()` iteriert, und `slistDir` zusätzlich für jeden Eintrag einen String
zusammenbaut. Named-Property-Zugriffe laufen über diesen Pfad; im Paket gibt es 182
`getNamedProp`-Aufrufstellen. Effektiv O(N·M) bei N Lookups und M Streams.

Zweiter Defekt an derselben Stelle: die gecachte Liste wird per Referenz zurückgegeben und
von Aufrufern mutiert — `ole_writer.py:822-823` macht
`entries = msg.listDir(...); entries.sort(key = len)` und sortiert damit den Cache in place.

### C2. Jeder Stream-Read kostet zwei Baum-Durchläufe ✅

`getStream` (`msg.py:712-713`) ruft erst `exists()`, dann `openstream()` — beides geht durch
`OleFileIO._find`. `_find` ist in `olefile` 0.47 ein linearer Scan über `node.kids` mit
`kid.name.lower() == name.lower()` je Kandidat, obwohl direkt daneben ein fertiges,
bereits lowercase-indiziertes `kids_dict` liegt, das ungenutzt bleibt. Also O(Geschwister)
pro Read, mit einer `.lower()`-Allokation pro Vergleich. `sExists` (`msg.py:454`) verdoppelt
das auf bis zu vier Durchläufe.

**Vorschlag:** ein `_findEntry`-Helper in `MSGFile`, der `kids_dict` nutzt und
`exists` + `openstream` zu einem Lookup zusammenzieht. Größter Einzelhebel, ohne Änderung
an `olefile`.

### C3. O(n²)-Dedupe bei Attachments und Recipients

`msg.py:886` und `extract_msg/msg_classes/message_base.py:1313` verwenden beide
`if dir_[0] not in attachmentDirs` — ein linearer Test auf einer Liste innerhalb der
Schleife über alle Storage-Einträge. Ein begleitendes `set` löst das.

Analog filtern `AttachmentBase.listDir` (`attachment_base.py:441`) und
`Recipient.listDir` (`extract_msg/recipient.py:264`) jeweils das Gesamt-Listing der
Nachricht, also O(Anhänge × Einträge).

### C4. Doppeltes Öffnen in `openMsg`

`extract_msg/open_msg.py:121-162`: nach Erkennung des `classType` wird `msg.close()` gerufen
und die Datei von vorn neu konstruiert (`return Message(path, **kwargs)`). Für
Top-Level-Dateien heißt das: FAT laden, Directory-Baum aufbauen, Property-Store und Named
Properties parsen — alles zweimal.

**Vorschlag:** entweder die geöffnete `OleFileIO`-Instanz an den finalen Konstruktor
durchreichen (das Ownership-Modell aus `msg.py:141-142` existiert bereits und wird für
eingebettete MSGs genau so genutzt), oder den `classType` vorab aus dem Property-Stream
lesen, ohne ein vollständiges `MSGFile` zu bauen.

### C5. Speicher: nichts streamt, Anhänge werden eifrig geladen

- `olefile`s `OleStream` ist eine `io.BytesIO`-Subklasse, die den kompletten Stream im
  Konstruktor materialisiert. `msg.py:714` ruft danach `stream.read()` — eine zweite
  Vollkopie. Spitzenlast pro Read etwa 2× Streamgröße.
- `extract_msg/attachments/attachment.py:40` lädt bereits im Konstruktor
  `self.__data = self.getStream('__substg1.0_37010102')`. Da `MSGFile.__init__` die
  Attachments antriggert (sofern nicht `delayAttachments=True`), belegt eine Nachricht mit
  200 MB Anhängen sofort 200 MB RAM.
- Der Export ist vollständig in-memory: `OleWriter.fromMsg` (`ole_writer.py:827`) holt jeden
  Stream als `bytes` und hält ihn, bevor `write()` überhaupt etwas ausgibt. `exportBytes`
  (`msg.py:527-531`) legt ein `BytesIO` obendrauf, also etwa 2× Dateigröße.

**Vorschlag:** `Attachment.data` auf `cached_property` umstellen (lazy statt eager) — kleiner,
gut testbarer Eingriff mit großer Wirkung auf den Peak-RSS.

---

## D. Weitere Writer-Befunde

| # | Schwere | Ort | Befund |
|---|---|---|---|
| D1 | hoch | `ole_writer.py:73` | ✅ `re.search('/\\\\:!', name)` ist kein Character-Class, sondern die Zeichen*folge* `/\:!`; `re.search(..., 'a/b')` ergibt `False`. Die Validierung greift also nie. `addEntry`/`editEntry`/`renameEntry` sind über `utils.inputToMsgPath` bzw. `constants.re.INVALID_OLE_PATH` abgesichert — `addOleEntry` (Zeile 709) aber nicht, und genau das übernimmt Namen ungeprüft aus der Quelldatei. Fix: `re.search(r'[/\\:!]', ...)`. |
| D2 | mittel | `ole_writer.py:535,557,568,577,592,645` | Ein `struct.pack` plus ein `f.write` pro 4-Byte-FAT-Eintrag. Bei 100 MB Output rund 200 000 Paare allein für die FAT. Batchbar über `struct.Struct(f'<{n}I').pack(*range(a, b))` oder Akkumulation in einem `bytearray`. |
| D3 | niedrig | `ole_writer.py:69,407` | ✅ `len(self.name) > 31` zählt Python-Zeichen statt UTF-16-Code-Units: 31 astrale Zeichen ergeben 124 Byte, `64s` schneidet still ab. Der Sortierschlüssel `(len(name), name.upper())` nutzt volles Unicode-Casing — `'straße'.upper()` wird `'STRASSE'` (6 → 7 Zeichen). [MS-CFB] 2.6.4 verlangt Code-Unit-Länge und längentreues Uppercasing. Bei ASCII-Streamnamen irrelevant, bei nutzerbenannten Storages nicht. |
| D4 | niedrig | `ole_writer.py:447-449` | Storages erhalten `startingSectorLocation = 0xFFFFFFFE`; [MS-CFB] 2.6.1 verlangt `0`. Leser ignorieren das Feld (Size ist 0), also benigne, aber eine echte Spec-Abweichung. |
| D5 | niedrig | `ole_writer.py:641-648` | ✅ Die innere Schleife `for x in range(...)` überschreibt die äußere Laufvariable `for x in entries`. Funktioniert nur, weil `x` danach nicht mehr gelesen wird. |
| D6 | niedrig | `ole_writer.py:450,642,656` | Dieselbe Mini-Stream-Klassifikation wird dreimal mit drei verschiedenen Prädikaten hergeleitet; Zeile 656 prüft den Typ gar nicht. Heute konsistent, aber ohne Assertion abgesichert — jede künftige Entry-Art mit Daten desynchronisiert MiniFAT und Mini-Stream still. |
| D7 | niedrig | `ole_writer.py:818,890,897` | Zeitstempel und State Bits des Root-Entry werden beim Klonen nie aus der Quelle übernommen, nur die CLSID. |
| D8 | latent | `ole_writer.py:317,377,500,511,614-615` | v3-Hardcodes (4 Dir-Entries pro Sektor, `& 3`, Dir-Sector-Count `0`), obwohl `__dirEntsPerSector` existiert und anderswo korrekt benutzt wird. Relevant erst, wenn v4 aktivierbar wird; `__version` hat derzeit keinen Setter (`ole_writer.py:114`). |
| D9 | latent | `ole_writer.py:411` | `entry.childTreeRoot = tree.value` setzt voraus, dass `RedBlackTree` nach Rotationen dasselbe Root-*Objekt* behält. Erklärt vermutlich den engen Pin `red-black-tree-mod>=1.20,<=1.23`. Hier nicht verifizierbar, da die Bibliothek in dieser Umgebung nicht installiert ist. |

Ausdrücklich positiv: `_treeSort` (`ole_writer.py:368-454`) baut einen echten
Rot-Schwarz-Baum mit korrekten Farben und Kindzeigern — keine degenerierte Kette, wie sie
in vielen CFB-Writern zu finden ist. Die Header-Felder sind bis auf D8 spec-konform, und
die Padding-Logik für MiniFAT und Mini-Stream stimmt.

---

## E. Zwei Bugs außerhalb des OLE-Themas

1. ✅ **Operator-Präzedenz in `getMultipleString`**, `msg.py:584`:

   ```python
   filename = self.fixPath(filename, prefix) + '101F' if self.areStringsUnicode else '101E'
   ```

   Python parst das als `(fixPath(...) + '101F') if unicode else '101E'`. Im
   Nicht-Unicode-Zweig wird `filename` damit zum nackten Literal `'101E'` — der Pfad ist
   weg, der Read schlägt fehl, und die Funktion gibt still `[]` zurück (Zeile 587). Die
   korrekte Klammerung steht direkt daneben in `getMultipleBinary` (`msg.py:555`).
   Betroffen sind alle Multiple-String-Properties in Nicht-Unicode-MSGs.

2. **Enum-gegen-String-Vergleich in `close()`**, `msg.py:420`:
   `if attachment.type == 'msg':` vergleicht `AttachmentType` mit `str`, ist also immer
   `False`. Eingebettete MSGs werden hier nie geschlossen. Heute harmlos, weil Kinder das
   Handle nicht besitzen; bricht, sobald sich das ändert.

---

## Empfohlene Reihenfolge

| Priorität | Maßnahme | Aufwand |
|---|---|---|
| 1 | DIFAT-Fix (A) plus Regressionstest mit synthetisch >14,6 MB großer Datei | klein |
| 2 | `listDir`-Cache-Early-Return (C1), Kopie statt Referenz zurückgeben | klein |
| 3 | `getStream`: ein Lookup statt zwei, über `kids_dict` (C2) | mittel |
| 4 | `msg.py:584` Klammerung, `msg.py:420` Enum-Vergleich (E) | trivial |
| 5 | Character-Class im Writer korrigieren (D1) | trivial |
| 6 | `Attachment.data` lazy (C5) | klein, API-sichtbar |
| 7 | `olefile`-Exceptions typbasiert, `parsing_issues` durchreichen (B1, B2) | mittel |
| 8 | FAT-Schreibschleifen batchen (D2) | klein |
| 9 | Doppeltes Öffnen in `openMsg` vermeiden (C4) | mittel, API-nah |
