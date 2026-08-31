# Specifica dell'algoritmo

Descrizione del nucleo di calcolo indipendente dall'implementazione, sufficiente a riscriverlo in C++
o C# per il Livello 2. Il codice Python in `src/hsmpace/core/` e' la realizzazione di riferimento e usa
solo aritmetica standard: nessuna libreria numerica, nessuno stato globale, nessuna dipendenza da
Excel o da Plotly.

Unita': metri, secondi, m/s, m/s2 per il moto; millimetri per spessori e larghezze.

## 1. Rappresentazione del moto

Ogni estremita' di un pezzo e' descritta da una sequenza contigua di segmenti uniformemente accelerati:

```
Segment { t0, t1, x0, v0, a }
x(t) = x0 + v0*(t - t0) + 0.5*a*(t - t0)^2
v(t) = v0 + a*(t - t0)
```

La posizione e' continua fra segmenti consecutivi; la velocita' puo' essere discontinua, cosa
fisicamente corretta ai bite e ai tail-out. Non esiste un passo di integrazione: le traiettorie sono
esatte.

Attraversamento di una posizione: risolvere `0.5*a*tau^2 + v0*tau + (x0 - X) = 0` e scartare le radici
fuori da `[t0, t1]` e quelle con velocita' di segno diverso da quello richiesto. Nel caso `a = 0` la
radice e' `tau = (X - x0)/v0`, e con `v0 = 0` non c'e' attraversamento.

## 2. Stato del pezzo

```
t            tempo corrente
x_head       posizione della testa materiale, sempre >= x_tail
x_tail       posizione della coda materiale
direction    +1 avanti, -1 indietro
v_lead       modulo della velocita' dell'estremita' che guida nel verso corrente
lam          produttoria dei lambda delle passate ingaggiate, inizialmente 1
engaged      elenco delle passate ingaggiate, ciascuna con la posizione della gabbia
next_pass    indice della prossima passata da ingaggiare
target       velocita' obiettivo dell'estremita' guida
zoom_factor  moltiplicatore cumulato dello zoom rolling, inizialmente 1
accel        accelerazione corrente, presa dall'asse che sta comandando
deferred     eventuale evento di sezione rinviato al disingaggio
reversing    vero mentre si decelera per invertire
```

Estremita' guida e trascinata:

```
direction = +1  ->  guida = testa,  trascinata = coda
direction = -1  ->  guida = coda,   trascinata = testa
```

Velocita' e accelerazione con segno:

```
v_guida        = direction * v_lead
v_trascinata   = direction * v_lead / lam
a_guida        = direction * a_lead
a_trascinata   = direction * a_lead / lam
```

dove `a_lead` vale `+accel` se `target > v_lead`, `-accel` se `target < v_lead`, altrimenti 0, e
`target` e' `target_nominale * zoom_factor`.

`lambda` di una passata: `(h_in * w_in) / (h_out * w_out)`. La lunghezza cresce spontaneamente, perche'
l'estremita' a valle di ogni gabbia ingaggiata e' piu' veloce di quella a monte; non va imposta.

## 3. Inizializzazione

* `t = t_release`, `x_head = x_start`, `x_tail = x_start - lunghezza_bramma`, `direction = +1`,
  `v_lead = 0`, `lam = 1`, `zoom_factor = 1`
* `target_nominale` = velocita' di avvicinamento della prima passata, cioe' il campo `approach_v` se
  presente, altrimenti `v_exit / lambda` della prima passata
* `accel` = accelerazione dell'apparecchiatura di partenza

## 4. Ciclo a eventi

A ogni iterazione l'accelerazione e' costante, quindi tutti gli attraversamenti si risolvono in forma
chiusa. Si calcolano i candidati, si prende il piu' vicino nel tempo, si emettono i due segmenti fino a
quell'istante e si applica l'evento.

Candidati:

1. **fine rampa**: `t + (target - v_lead) / a_lead`, se `a_lead != 0`
2. **bite** della prossima passata: attraversamento della posizione della gabbia da parte
   dell'estremita' guida, nel verso della passata. Solo se il verso della passata coincide con quello
   corrente, non si sta invertendo, e la gabbia e' **ancora davanti**:
   `direction * (x_gabbia - x_guida) > tolleranza`. Senza quest'ultima condizione, subito dopo un bite
   l'estremita' guida si trova esattamente sulla gabbia e una seconda passata sullo stesso stand
   morderebbe nello stesso istante.
3. **tail-out** di ogni passata ingaggiata: attraversamento della posizione della gabbia da parte
   dell'estremita' trascinata
4. **evento di velocita'**: attraversamento della posizione di trigger da parte dell'estremita' guida,
   nel verso dichiarato dall'evento. Un evento non si riattiva nello stesso istante in cui e' scattato;
   gli eventi di sezione sono ignorati mentre si sta invertendo.
5. **fine corsa**: attraversamento della posizione dell'avvolgitore da parte dell'estremita'
   trascinata, solo quando non ci sono passate residue ne' gabbie ingaggiate

Se non esiste alcun candidato la simulazione e' mal posta: se restano passate da eseguire, la prossima
non e' raggiungibile nel verso indicato; altrimenti manca un comando di velocita' in coda al percorso.
In entrambi i casi si termina con un errore esplicito, mai con un ciclo infinito.

### Applicazione degli eventi

**Fine rampa**: `v_lead = target`. Se si sta invertendo e il target era zero, il pezzo e' fermo: si
avvia l'attesa del `reversing_delay` della prossima passata.

**Bite** della passata `p`:

```
lam     = lam * lambda(p)
v_lead  = v_lead * lambda(p)      // resta continua l'estremita' trascinata
engaged = engaged + p
target_nominale = v_exit(p)
accel   = accelerazione della gabbia
```

Se la passata definisce uno zoom, si registra un evento di velocita' relativo con trigger a
`x_gabbia + zoom_trigger`, verso avanti, valido anche durante la laminazione.

**Tail-out** della passata `p`:

```
lam = lam / lambda(p)             // resta continua l'estremita' guida
engaged = engaged - p
```

Se non resta nulla di ingaggiato: si applica l'eventuale evento differito, poi, se la prossima passata
ha verso opposto, si entra in inversione con `target_nominale = 0`, `zoom_factor = 1` e accelerazione
della gabbia appena liberata.

**Evento di velocita'**: se ci sono gabbie ingaggiate e l'evento non e' marcato valido in laminazione,
viene messo da parte come differito, l'ultimo che arriva sostituisce il precedente. Altrimenti, se
l'evento e' relativo si moltiplica `zoom_factor`, se e' assoluto si assegna `target_nominale`.

**Attesa di inversione**: si emettono due segmenti a velocita' nulla per la durata del
`reversing_delay`, poi si inverte `direction`, si assegna la velocita' di avvicinamento della prossima
passata e l'accelerazione della sua gabbia.

## 5. Post-elaborazione

* **testa virtuale**: la traiettoria della testa cosi' come e' stata integrata, non vincolata
  dall'avvolgitore. E' quella che comanda il trigger dello zoom rolling.
* **testa fisica**: la testa virtuale limitata superiormente alla posizione dell'avvolgitore. Il
  troncamento introduce un nuovo nodo all'istante di attraversamento, calcolato in forma chiusa.
* **verifica di conservazione**: la lunghezza finale integrata deve coincidere con
  `L_bramma * (h_bramma * w_bramma) / (h_finale * w_finale)`. Con questo modello coincidono per
  costruzione: uno scarto segnala un errore di input o di implementazione.

## 6. Bilancio di massa nel tandem

Nel finitore il nastro fra due gabbie ha lunghezza fissa, quindi il bilancio di massa non e' una
verifica ma un vincolo: velocita' inserite incoerenti descriverebbero un moto impossibile. Per ogni
gruppo di gabbie che porta la stessa etichetta di gruppo e contiene una passata marcata master:

```
flusso  = v_exit(master) * h_out(master) * w_out(master)
v_exit(i) = flusso / (h_out(i) * w_out(i))
```

Gli scostamenti rispetto ai valori inseriti vengono riportati, non silenziati.

## 7. Gap fra pezzi

L'estremita' posteriore di un pezzo e' `min(testa, coda)` e quella anteriore `max(testa, coda)`.
Poiche' la testa materiale resta sempre l'estremita' geometricamente piu' a valle, anche durante le
passate inverse, le due espressioni si riducono rispettivamente alla coda del pezzo davanti e alla
testa di quello dietro. L'invariante `x_head >= x_tail` va verificato, non assunto.

```
gap(t) = coda_davanti(t) - testa_dietro(t)
```

La differenza di due traiettorie a segmenti e' una funzione **quadratica a tratti**: si fondono i nodi
delle due traiettorie e su ogni intervallo si ottiene

```
f(t) = c0 + c1*(t - t0) + c2*(t - t0)^2
c0 = xA(t0) - xB(t0)      c1 = vA(t0) - vB(t0)      c2 = (aA - aB) / 2
```

Il minimo si cerca sugli estremi di ogni tratto e sul vertice, quando cade all'interno. Il primo
istante in cui il gap scende sotto una soglia si ottiene risolvendo `f(t) = soglia` su ogni tratto.
Entrambi sono esatti: non c'e' campionamento.

Il gap temporale al punto critico e' l'intervallo fra il passaggio della coda del pezzo davanti e
l'arrivo della testa di quello dietro nella stessa posizione, ottenuto cercando l'ultimo
attraversamento della posizione critica da parte della coda del pezzo davanti prima dell'istante
critico.

Vanno confrontate tutte le coppie di pezzi che coesistono in linea, non solo quelle adiacenti: con lo
sbozzatore reversibile il vincolo cade spesso fra il pezzo N e N+2.

## 8. Studi sul pacing

In modalita' open-loop i pezzi sono disaccoppiati: ogni prodotto si simula una volta sola e le copie si
ottengono traslando le traiettorie nel tempo di `i * pacing`.

* **curva gap-vs-pacing**: per ogni valore della scansione si costruisce la sequenza e si prende il
  minimo su tutte le coppie.
* **pacing minimo ammissibile**: con le passate reversibili il gap minimo **non e' monotono** nel
  pacing, quindi non si applica una bisezione cieca. Si scandisce la curva, si prende l'ultimo punto
  non ammissibile e si raffina per bisezione l'intervallo immediatamente successivo.
* **robustezza**: si perturbano le velocita' di passata entro una tolleranza, i tempi morti e gli
  istanti di rilascio con dispersione gaussiana, si riapplica il bilancio di massa del tandem, si
  risimula ogni pezzo in modo indipendente e si conta la frazione di run che viola la soglia. La
  perturbazione va applicata **prima** del bilancio di massa, cosi' nel tandem conta la sola
  perturbazione della gabbia master e la schedule resta fisica.

## 9. Costi

Una simulazione completa di un impianto con tredici passate costa circa 0,4 ms e produce una
cinquantina di segmenti per estremita'. Una scansione di un centinaio di valori di pacing costa
qualche decina di millisecondi, un Monte Carlo di diecimila run qualche secondo. Il collo di bottiglia
non e' il calcolo ma il disegno: campionare le traiettorie a passo fisso produrrebbe milioni di punti
e renderebbe inutilizzabile l'interfaccia, mentre i segmenti si disegnano con i soli nodi, suddividendo
unicamente i tratti accelerati.
