# Przegląd literatury – komunikacja i synchronizacja urządzeń

## 1. Wprowadzenie

Projektowany trenażer strzelecki wykorzystuje dwa niezależne źródła danych: moduł oparty na mikrokontrolerze ESP32-C3, pozyskujący pomiary z jednostki inercyjnej MPU-6050 oraz sygnał naciśnięcia spustu, a także kamerę współpracującą z komputerem Raspberry Pi, rejestrującą położenie plamki lasera na tarczy. Połączenie tych danych wymaga zarówno odpowiedniego sposobu transmisji, jak i synchronizacji czasowej. W szczególności chwila otrzymania pakietu przez komputer nie musi odpowiadać chwili wykonania pomiaru, ponieważ przesyłanie i obsługa danych mogą wprowadzać opóźnienia o zmiennej wartości.

W przeglądzie uwzględniono prace dotyczące wydajności protokołów komunikacyjnych stosowanych w urządzeniach IoT, transmisji o małych opóźnieniach oraz synchronizacji czujników inercyjnych z obrazem kamery. Celem jest wskazanie metod przydatnych do zaprojektowania wspólnej osi czasu dla trajektorii punktu celowania, ruchu repliki i zdarzenia naciśnięcia spustu.

## 2. Przegląd publikacji

### 2.1. *Assessing MQTT, CoAP, and HTTP Performance in Real-Life Scenarios on ESP32-Based IoT Nodes* [1]

Autorzy porównują trzy protokoły warstwy aplikacji — MQTT, CoAP i HTTP — w lokalnym środowisku IoT wykorzystującym mikrokontrolery ESP32-C6 i ESP32-S3. Analizie poddano opóźnienie realizacji transakcji oraz skuteczność transmisji niewielkich komunikatów o rozmiarach 16, 64 i 256 bajtów. Badania przeprowadzono w sieci Wi-Fi 2,4 GHz, przy kontrolowanych warunkach i 30 powtórzeniach dla każdej konfiguracji.

W opisanym środowisku CoAP uzyskał najniższe średnie opóźnienie transakcji, MQTT zajął kolejne miejsce, a HTTP charakteryzował się zdecydowanie większym narzutem czasowym. Należy jednak podkreślić, że badano przede wszystkim pojedyncze transakcje z ponownym nawiązywaniem połączeń, a nie ciągłą transmisję przy utrzymywanej sesji. Wyniki nie stanowią zatem bezpośredniego pomiaru opóźnienia strumieniowania danych z czujnika.

**Możliwość wykorzystania w projekcie:** publikacja stanowi podstawę do porównania sposobów przesyłania niewielkich pakietów telemetrycznych z ESP32-C3 do Raspberry Pi. Uzasadnia rozważenie lekkich rozwiązań, takich jak CoAP, MQTT lub komunikacja oparta na UDP, zamiast wykonywania osobnego żądania HTTP dla każdej próbki. Ostateczny wybór powinien zostać potwierdzony pomiarami na docelowej płytce i w docelowej konfiguracji sieci.

### 2.2. *Performance Evaluation of ESP-NOW for Low-Latency Indoor IoT Systems* [2]

W publikacji oceniono wydajność bezprzewodowej transmisji ESP-NOW, umożliwiającej bezpośrednią komunikację między urządzeniami ESP32 bez korzystania z klasycznego punktu dostępowego Wi-Fi. Autorzy zbudowali stanowisko z trzema mikrokontrolerami i badali opóźnienia jednostronnej transmisji danych przy równoczesnym obciążeniu sieci. Eksperymenty wykonano w warunkach wewnętrznych, w odległościach 20, 50 i 70 m, analizując między innymi medianę opóźnienia, zmienność oraz wysokie percentyle rozkładu.

Wyniki wskazują na niskie typowe opóźnienia transmisji, ale jednocześnie pokazują, że zwiększenie odległości wpływa na rozrzut wyników i występowanie sporadycznych, znacznie większych opóźnień. Istotnym elementem badań jest zastosowanie programowej synchronizacji urządzeń na potrzeby pomiaru opóźnienia jednostronnego. Praca pokazuje, że niska mediana opóźnienia nie oznacza jeszcze deterministycznego czasu dostarczenia wszystkich pakietów.

**Możliwość wykorzystania w projekcie:** artykuł może posłużyć do oceny, czy ESP-NOW jest wart uwzględnienia jako alternatywny sposób przesyłania danych z modułu na replice. Ponieważ ESP-NOW jest rozwiązaniem przeznaczonym przede wszystkim do komunikacji między zgodnymi urządzeniami Espressif, bezpośredni odbiór danych na Raspberry Pi wymagałby dodatkowego rozwiązania, na przykład modułu pośredniczącego ESP32. Z tego powodu prostsza sieć Wi-Fi może okazać się praktyczniejsza. Metodyka pomiaru opóźnień i analizy percentyli może natomiast zostać wykorzystana niezależnie od wybranego protokołu.

### 2.3. *Synchronization of External Inertial Sensors and Built-in Camera on Mobile Devices* [3]

Autorzy rozpatrują problem synchronizacji danych z zewnętrznych czujników inercyjnych IMU oraz kamery urządzenia mobilnego. W eksperymencie dane z czujników przesyłano bezprzewodowo do smartfona, który równocześnie rejestrował obraz. Wskazano, że znaczniki czasu nadawane podczas odbioru danych przez system operacyjny nie muszą odzwierciedlać rzeczywistych chwil ich pozyskania. Wynika to między innymi ze zmiennych opóźnień transmisji, obsługi zdarzeń oraz różnic pomiędzy nominalną i faktyczną częstotliwością próbkowania.

Autorzy przedstawiają metodę synchronizacji wykorzystującą analizę przesunięcia między sekwencjami próbek. Zamiast dopasowywać każdy pomiar wyłącznie na podstawie najbliższego znacznika czasu, stosują statystyczną estymację przesunięcia z wykorzystaniem mediany w przesuwającym się oknie. Takie rozwiązanie ogranicza wpływ przypadkowych opóźnień odbioru i umożliwia dostosowanie do zmian relacji czasowej między strumieniami. Publikacja przedstawia również procedury weryfikacji jakości synchronizacji z użyciem zdarzeń referencyjnych.

**Możliwość wykorzystania w projekcie:** jest to jedna z najbardziej bezpośrednio związanych z tematem prac. W trenażerze strumień IMU i zdarzeń spustu pochodzi z ESP32, natomiast obrazy są rejestrowane przez kamerę Raspberry Pi. Publikacja uzasadnia zapisywanie znaczników czasu pomiarów u źródła, wykrywanie brakujących próbek oraz estymację przesunięcia czasowego między strumieniami. Opisana metoda może stanowić punkt odniesienia dla synchronizacji programowej, jednak wymaga adaptacji, ponieważ w projektowanym układzie kamera i IMU pracują na dwóch odrębnych urządzeniach z własnymi zegarami.

### 2.4. *3-D Motion Estimation and Online Temporal Calibration for Camera-IMU Systems* [4]

Publikacja dotyczy kalibracji przesunięcia czasowego między kamerą a jednostką inercyjną w systemach łączących dane obrazowe i pomiary ruchu. Autorzy wskazują, że nawet poprawnie zarejestrowane dane mogą prowadzić do błędnych wyników fuzji, jeżeli nie odpowiadają tym samym chwilom czasowym. Zaproponowano metodę, w której przesunięcie czasowe jest jednym z parametrów estymowanych na bieżąco przez rozszerzony filtr Kalmana (EKF), równolegle z parametrami ruchu.

Metoda została przedstawiona w kontekście estymacji ruchu w przestrzeni trójwymiarowej, w tym systemów wizyjno-inercyjnych. Jej zaletą jest możliwość uwzględniania zarówno stałego, jak i zmiennego przesunięcia czasowego. W porównaniu z prostym jednorazowym wyrównaniem znaczników czasu rozwiązanie ma szersze możliwości, ale wymaga bardziej złożonego modelu obserwacji i estymacji.

**Możliwość wykorzystania w projekcie:** praca dostarcza teoretycznego uzasadnienia konieczności kompensowania przesunięcia między obrazem i IMU. Nie ma potrzeby przenoszenia pełnego algorytmu EKF do trenażera, jeżeli wystarczająca okaże się prostsza synchronizacja oparta na znacznikach czasu i okresowej korekcji. Publikacja może natomiast stanowić podstawę do omówienia bardziej zaawansowanych metod oraz wskazania kierunku rozwoju systemu, gdyby zmienność przesunięcia czasowego uniemożliwiała uzyskanie wymaganej dokładności.

### 2.5. *Clock Synchronization for Wireless Sensor Networks: A Survey* [5]

Jest to praca przeglądowa poświęcona synchronizacji zegarów w bezprzewodowych sieciach czujnikowych. Autorzy porównują podejścia do ustalania wspólnej podstawy czasowej z uwzględnieniem dokładności, kosztu, złożoności oraz ograniczeń urządzeń. Praca podkreśla, że w systemach rozproszonych lokalne zegary nie wskazują automatycznie tej samej chwili i mogą stopniowo zmieniać wzajemne przesunięcie.

Publikacja pomaga uporządkować pojęcia takie jak przesunięcie zegarów, dryft, niepewność transmisji czy wymiana komunikatów synchronizacyjnych. Jest szczególnie przydatna jako podstawa teoretyczna: pozwala oddzielić synchronizację zegarów urządzeń od późniejszego dopasowywania zapisanych próbek.

**Możliwość wykorzystania w projekcie:** opracowanie może stanowić podstawę rozdziału teoretycznego dotyczącego synchronizacji ESP32-C3 i Raspberry Pi. Na jego podstawie można uzasadnić zastosowanie okresowej wymiany wiadomości synchronizacyjnych, estymacji wzajemnego przesunięcia i dryftu zegarów oraz oznaczania pomiarów lokalnym, monotonicznym czasem. Przydatne będzie również przy definiowaniu metryk oceny: błędu synchronizacji, stabilności przesunięcia i zmienności opóźnienia komunikacji.

## 3. Wnioski z przeglądu literatury

Przedstawione publikacje wskazują, że wybór protokołu przesyłania danych i synchronizacja czasowa są odrębnymi zagadnieniami. Wyniki badań nad MQTT, CoAP i ESP-NOW [1, 2] pozwalają porównać opóźnienia komunikacji, lecz nawet szybka transmisja nie zapewnia automatycznie zgodności czasowej pomiarów. Z kolei badania systemów kamera–IMU [3, 4] pokazują, że konieczne jest uwzględnienie momentu rzeczywistej rejestracji danych oraz błędów wynikających z obsługi transmisji i rozbieżności zegarów. Przegląd metod synchronizacji sieci czujnikowych [5] dostarcza podstaw do wyboru odpowiedniego mechanizmu wyrównania czasu.

Na potrzeby projektowanego trenażera zasadne wydaje się rozważenie architektury, w której ESP32-C3 przypisuje lokalne, monotoniczne znaczniki czasu do próbek IMU i zdarzeń spustu, a Raspberry Pi zapisuje możliwie bliskie rzeczywistemu momentowi ekspozycji znaczniki czasu klatek kamery. Dane telemetryczne mogą być przesyłane przez Wi-Fi, przy czym chwila odbioru pakietu nie powinna stanowić jedynej podstawy synchronizacji. Dodatkowo przydatne będzie numerowanie próbek, aby wykrywać ich utratę lub nieprawidłową kolejność.

Kolejnym etapem powinno być opracowanie i przetestowanie mechanizmu estymacji relacji między zegarami ESP32-C3 i Raspberry Pi, obejmującego przesunięcie czasowe oraz ewentualny dryft. Uzyskaną synchronizację należy zweryfikować eksperymentalnie, na przykład przez zarejestrowanie wspólnego zdarzenia w sygnale czujnika i obrazie. Ostateczny dobór protokołu i algorytmu powinien zależeć od wyników pomiarów na rzeczywistym stanowisku, a nie wyłącznie od wartości opóźnienia podanych w literaturze.

## 4. Bibliografia

[1] A. Kirilov, D. Chikurtev, G. Nedeltcheva, P. So, **“Assessing MQTT, CoAP, and HTTP Performance in Real-Life Scenarios on ESP32-Based IoT Nodes”**, *Engineering Proceedings*, vol. 150, nr 1, art. 126, MDPI, 2026. https://doi.org/10.3390/engproc2026150126

[2] P. Levush, A. Luchechko, **“Performance Evaluation of ESP-NOW for Low-Latency Indoor IoT Systems”**, *Advances in Cyber-Physical Systems*, vol. 11, 2026, Lviv Polytechnic National University. https://doi.org/10.23939/acps2026.01.001

[3] F. Malawski, K. Kapela, M. Krupa, **“Synchronization of External Inertial Sensors and Built-in Camera on Mobile Devices”**, *2023 IEEE Symposium Series on Computational Intelligence (SSCI)*, IEEE, 2023. https://doi.org/10.1109/SSCI52147.2023.10371853

[4] M. Li, A. I. Mourikis, **“3-D Motion Estimation and Online Temporal Calibration for Camera-IMU Systems”**, *2013 IEEE International Conference on Robotics and Automation (ICRA)*, IEEE, 2013. https://doi.org/10.1109/ICRA.2013.6631398

[5] B. Sundararaman, U. Buy, A. D. Kshemkalyani, **“Clock Synchronization for Wireless Sensor Networks: A Survey”**, *Ad Hoc Networks*, vol. 3, nr 3, s. 281–323, Elsevier, 2005. https://doi.org/10.1016/j.adhoc.2005.01.002
