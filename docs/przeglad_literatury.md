# Przegląd literatury – komunikacja i synchronizacja urządzeń

## 1. Wprowadzenie

Projektowany trenażer strzelecki wykorzystuje dwa niezależne źródła danych: moduł oparty na mikrokontrolerze ESP32-C3, pozyskujący pomiary z jednostki inercyjnej MPU-6050 oraz sygnał naciśnięcia spustu, a także kamerę współpracującą z komputerem Raspberry Pi, rejestrującą położenie plamki lasera na tarczy. Połączenie tych danych wymaga zarówno odpowiedniego sposobu transmisji, jak i synchronizacji czasowej. W szczególności chwila otrzymania pakietu przez komputer nie musi odpowiadać chwili wykonania pomiaru, ponieważ przesyłanie i obsługa danych mogą wprowadzać opóźnienia o zmiennej wartości.

W przeglądzie uwzględniono prace dotyczące wydajności protokołów komunikacyjnych stosowanych w urządzeniach IoT, transmisji o małych opóźnieniach oraz synchronizacji czujników inercyjnych z obrazem kamery. Celem jest wskazanie metod przydatnych do zaprojektowania wspólnej osi czasu dla trajektorii punktu celowania, ruchu repliki i zdarzenia naciśnięcia spustu.

## 2. Przegląd literatury

### 2.1. Porównanie protokołów komunikacyjnych dla urządzeń IoT

Kirilov i współautorzy porównali trzy protokoły warstwy aplikacji — MQTT, CoAP i HTTP — w lokalnym środowisku IoT wykorzystującym mikrokontrolery ESP32-C6 i ESP32-S3. Analizie poddano opóźnienie realizacji transakcji oraz skuteczność transmisji niewielkich komunikatów o rozmiarach 16, 64 i 256 bajtów. Badania przeprowadzono w sieci Wi-Fi 2,4 GHz, przy kontrolowanych warunkach i 30 powtórzeniach dla każdej konfiguracji. [1]

Wyniki badania wskazują, że w opisanym środowisku CoAP uzyskał najniższe średnie opóźnienie transakcji, MQTT zajął kolejne miejsce, a HTTP charakteryzował się zdecydowanie większym narzutem czasowym. Należy jednak podkreślić, że badano przede wszystkim pojedyncze transakcje z ponownym nawiązywaniem połączeń, a nie ciągłą transmisję przy utrzymywanej sesji. Wyniki nie stanowią zatem bezpośredniego pomiaru opóźnienia strumieniowania danych z czujnika. [1]

**Możliwość wykorzystania w projekcie:** publikacja stanowi podstawę do porównania sposobów przesyłania niewielkich pakietów telemetrycznych z ESP32-C3 do Raspberry Pi. Uzasadnia rozważenie lekkich rozwiązań, takich jak CoAP, MQTT lub komunikacja oparta na UDP, zamiast wykonywania osobnego żądania HTTP dla każdej próbki. Ostateczny wybór powinien zostać potwierdzony pomiarami na docelowej płytce i w docelowej konfiguracji sieci.

### 2.2. Transmisja bezprzewodowa o małych opóźnieniach

Levush i Luchechko ocenili wydajność bezprzewodowej transmisji ESP-NOW, umożliwiającej bezpośrednią komunikację między urządzeniami ESP32 bez korzystania z klasycznego punktu dostępowego Wi-Fi. Autorzy zbudowali stanowisko z trzema mikrokontrolerami i badali opóźnienia jednostronnej transmisji danych przy równoczesnym obciążeniu sieci. Eksperymenty wykonano w warunkach wewnętrznych, w odległościach 20, 50 i 70 m, analizując między innymi medianę opóźnienia, zmienność oraz wysokie percentyle rozkładu. [2]

Wyniki badań wskazują na niskie typowe opóźnienia transmisji, ale jednocześnie pokazują, że zwiększenie odległości wpływa na rozrzut wyników i występowanie sporadycznych, znacznie większych opóźnień. Istotnym elementem badań jest zastosowanie programowej synchronizacji urządzeń na potrzeby pomiaru opóźnienia jednostronnego. Praca pokazuje, że niska mediana opóźnienia nie oznacza jeszcze deterministycznego czasu dostarczenia wszystkich pakietów. [2]

**Możliwość wykorzystania w projekcie:** artykuł może posłużyć do oceny, czy ESP-NOW jest wart uwzględnienia jako alternatywny sposób przesyłania danych z modułu na replice. Ponieważ ESP-NOW jest rozwiązaniem przeznaczonym przede wszystkim do komunikacji między zgodnymi urządzeniami Espressif, bezpośredni odbiór danych na Raspberry Pi wymagałby dodatkowego rozwiązania, na przykład modułu pośredniczącego ESP32. Z tego powodu prostsza sieć Wi-Fi może okazać się praktyczniejsza. Metodyka pomiaru opóźnień i analizy percentyli może natomiast zostać wykorzystana niezależnie od wybranego protokołu.

### 2.3. Synchronizacja zewnętrznych czujników inercyjnych z kamerą

Malawski, Kapela i Krupa rozpatrują problem synchronizacji danych z zewnętrznych czujników inercyjnych IMU oraz kamery urządzenia mobilnego. W eksperymencie dane z czujników przesyłano bezprzewodowo do smartfona, który równocześnie rejestrował obraz. Wskazano, że znaczniki czasu nadawane podczas odbioru danych przez system operacyjny nie muszą odzwierciedlać rzeczywistych chwil ich pozyskania. Wynika to między innymi ze zmiennych opóźnień transmisji, obsługi zdarzeń oraz różnic pomiędzy nominalną i faktyczną częstotliwością próbkowania. [3]

W publikacji przedstawiono metodę synchronizacji wykorzystującą analizę przesunięcia między sekwencjami próbek. Zamiast dopasowywać każdy pomiar wyłącznie na podstawie najbliższego znacznika czasu, stosują statystyczną estymację przesunięcia z wykorzystaniem mediany w przesuwającym się oknie. Takie rozwiązanie ogranicza wpływ przypadkowych opóźnień odbioru i umożliwia dostosowanie do zmian relacji czasowej między strumieniami. Publikacja przedstawia również procedury weryfikacji jakości synchronizacji z użyciem zdarzeń referencyjnych. [3]

**Możliwość wykorzystania w projekcie:** jest to jedna z najbardziej bezpośrednio związanych z tematem prac. W trenażerze strumień IMU i zdarzeń spustu pochodzi z ESP32, natomiast obrazy są rejestrowane przez kamerę Raspberry Pi. Publikacja uzasadnia zapisywanie znaczników czasu pomiarów u źródła, wykrywanie brakujących próbek oraz estymację przesunięcia czasowego między strumieniami. Opisana metoda może stanowić punkt odniesienia dla synchronizacji programowej, jednak wymaga adaptacji, ponieważ w projektowanym układzie kamera i IMU pracują na dwóch odrębnych urządzeniach z własnymi zegarami.

### 2.4. Kalibracja przesunięcia czasowego między obrazem a pomiarami IMU

Li i Mourikis analizują kalibrację przesunięcia czasowego między kamerą a jednostką inercyjną w systemach łączących dane obrazowe i pomiary ruchu. Autorzy wskazują, że nawet poprawnie zarejestrowane dane mogą prowadzić do błędnych wyników fuzji, jeżeli nie odpowiadają tym samym chwilom czasowym. Zaproponowano metodę, w której przesunięcie czasowe jest jednym z parametrów estymowanych na bieżąco przez rozszerzony filtr Kalmana (EKF), równolegle z parametrami ruchu. [4]

Metodę przedstawiono w kontekście estymacji ruchu w przestrzeni trójwymiarowej, w tym systemów wizyjno-inercyjnych. Jej zaletą jest możliwość uwzględniania zarówno stałego, jak i zmiennego przesunięcia czasowego. W porównaniu z prostym jednorazowym wyrównaniem znaczników czasu rozwiązanie ma szersze możliwości, ale wymaga bardziej złożonego modelu obserwacji i estymacji. [4]

**Możliwość wykorzystania w projekcie:** praca dostarcza teoretycznego uzasadnienia konieczności kompensowania przesunięcia między obrazem i IMU. Nie ma potrzeby przenoszenia pełnego algorytmu EKF do trenażera, jeżeli wystarczająca okaże się prostsza synchronizacja oparta na znacznikach czasu i okresowej korekcji. Publikacja może natomiast stanowić podstawę do omówienia bardziej zaawansowanych metod oraz wskazania kierunku rozwoju systemu, gdyby zmienność przesunięcia czasowego uniemożliwiała uzyskanie wymaganej dokładności.

### 2.5. Synchronizacja zegarów w rozproszonych sieciach czujników

Sundararaman, Buy i Kshemkalyani przedstawiają przegląd metod synchronizacji zegarów w bezprzewodowych sieciach czujnikowych. Autorzy porównują podejścia do ustalania wspólnej podstawy czasowej z uwzględnieniem dokładności, kosztu, złożoności oraz ograniczeń urządzeń. Praca podkreśla, że w systemach rozproszonych lokalne zegary nie wskazują automatycznie tej samej chwili i mogą stopniowo zmieniać wzajemne przesunięcie. [5]

Opracowanie pomaga uporządkować pojęcia takie jak przesunięcie zegarów, dryft, niepewność transmisji czy wymiana komunikatów synchronizacyjnych. Jest szczególnie przydatna jako podstawa teoretyczna: pozwala oddzielić synchronizację zegarów urządzeń od późniejszego dopasowywania zapisanych próbek. [5]

**Możliwość wykorzystania w projekcie:** opracowanie może stanowić podstawę rozdziału teoretycznego dotyczącego synchronizacji ESP32-C3 i Raspberry Pi. Na jego podstawie można uzasadnić zastosowanie okresowej wymiany wiadomości synchronizacyjnych, estymacji wzajemnego przesunięcia i dryftu zegarów oraz oznaczania pomiarów lokalnym, monotonicznym czasem. Przydatne będzie również przy definiowaniu metryk oceny: błędu synchronizacji, stabilności przesunięcia i zmienności opóźnienia komunikacji.

### 2.6. Podstawy transmisji w sieciach komputerowych

Peterson i Davie w podręczniku *Computer Networks: A Systems Approach* przedstawiają komunikację sieciową jako współdziałanie wielu warstw, od przesyłania ramek po mechanizmy transportowe i protokoły aplikacyjne. Omawiają między innymi usługi transportowe, niezawodność przesyłania oraz znaczenie opóźnień i przepustowości. Podręcznik pozwala odróżnić cechy samego protokołu od właściwości całego toru komunikacyjnego. [6]

**Możliwość wykorzystania w projekcie:** wiedza ta może posłużyć do uporządkowanego porównania TCP i UDP oraz osadzenia MQTT i CoAP we właściwym kontekście. W projektowanym systemie należy rozważyć kompromis pomiędzy łatwością obsługi transmisji, gwarancjami dostarczenia pakietu i zmiennością opóźnienia. Nie można przy tym utożsamiać niezawodnego dostarczenia danych z dokładną synchronizacją czasu pomiarów.

### 2.7. Sieciowa synchronizacja czasu i wymiana znaczników

Dokument RFC 5905 definiuje protokół Network Time Protocol w wersji 4, wykorzystywany do synchronizowania zegarów komputerów pracujących w sieci. Opisuje wymianę znaczników czasu pomiędzy urządzeniami oraz algorytmy służące do szacowania przesunięcia zegara i opóźnienia wymiany komunikatów. W metodzie tej istotne jest uwzględnienie czasów wysłania i odebrania wiadomości po obu stronach połączenia. [7]

**Możliwość wykorzystania w projekcie:** mechanizm czterech znaczników czasu może stanowić punkt wyjścia do opracowania lekkiej synchronizacji między ESP32-C3 i Raspberry Pi. Samo zastosowanie NTP nie gwarantuje jednak błędu rzędu 1 ms w konkretnym układzie, szczególnie przy komunikacji Wi-Fi. Dokładność należy wyznaczyć eksperymentalnie, a częstotliwość korekcji dostosować do zmierzonego dryftu zegarów.

### 2.8. Obsługa komunikacji i pomiaru czasu w ESP32-C3

Oficjalny *ESP-IDF Programming Guide* firmy Espressif Systems dokumentuje interfejsy programistyczne mikrokontrolera ESP32-C3, w tym obsługę Wi-Fi, timerów, zadań oraz urządzeń peryferyjnych. Opisuje dostępne źródła czasu i mechanizmy uzyskiwania znaczników o wysokiej rozdzielczości. Dokumentacja dotyczy konkretnej platformy sprzętowej, dlatego uzupełnia ogólne publikacje naukowe o możliwości implementacyjne. [8]

**Możliwość wykorzystania w projekcie:** jest to podstawowe źródło podczas implementacji kodu pobierającego odczyty IMU, wykrywającego zdarzenie spustu i wysyłającego pakiety do Raspberry Pi. Pozwala dobrać sposób nadawania lokalnych, monotonicznych znaczników czasu i rozdzielić pozyskiwanie danych od transmisji. Warto pamiętać, że rozdzielczość timera nie jest równoznaczna z rzeczywistą dokładnością synchronizacji dwóch urządzeń.

### 2.9. Parametry jednostki inercyjnej i interfejs I²C

Specyfikacja *MPU-6000/MPU-6050 Product Specification* opisuje parametry trójosiowego żyroskopu i akcelerometru, zakresy pomiarowe, zasilanie oraz możliwości komunikacyjne układu. Dla MPU-6050 istotna jest obsługa interfejsu I²C i konfiguracja częstotliwości pozyskiwania danych. Dokumentacja producenta stanowi źródło informacji o ograniczeniach fizycznego czujnika, które nie wynikają z samego algorytmu komunikacji. [9]

**Możliwość wykorzystania w projekcie:** parametry te są potrzebne do dobrania zakresów pomiarowych, częstości próbkowania oraz sposobu podłączenia MPU-6050 do ESP32-C3. Podczas projektowania należy oddzielić chwilę wygenerowania nowej próbki przez czujnik od chwili jej odczytu przez mikrokontroler. Do szczegółów rejestrów i konfiguracji urządzenia konieczne może być dodatkowe odwołanie do *Register Map and Descriptions* producenta.

### 2.10. Rejestracja obrazu i znaczniki czasu kamery Raspberry Pi

Dokumentacja *The Picamera2 Library* wydawana przez Raspberry Pi przedstawia programową obsługę kamer oraz metadane towarzyszące przechwyconym klatkom. Jednym z opisanych pól jest `SensorTimestamp`, odnoszące się do momentu początku ramki na poziomie czujnika obrazu i wyrażane w nanosekundach względem uruchomienia systemu. Pozwala to na bardziej precyzyjne przypisanie czasu do obrazu niż zapis chwili, w której aplikacja odebrała gotową klatkę. [10]

**Możliwość wykorzystania w projekcie:** podczas akwizycji obrazu na Raspberry Pi można zapisywać `SensorTimestamp` wraz z identyfikatorem klatki i wynikiem detekcji punktu laserowego. Ułatwi to późniejsze dopasowanie trajektorii do próbek IMU i momentu spustu. Trzeba jednak zweryfikować faktyczną dostępność oraz znaczenie tego pola dla wybranego modelu kamery i konfiguracji sterownika; nie jest to automatycznie czas ekspozycji każdej linii obrazu.

### 2.11. Projektowanie układu elektronicznego i separacja sygnałów

Horowitz i Hill w podręczniku *The Art of Electronics* omawiają praktyczne zasady projektowania układów analogowych i cyfrowych, w tym dobór elementów, zasilanie, interfejsowanie sygnałów logicznych i ograniczanie zakłóceń. Zagadnienia te mają szczególne znaczenie w systemach łączących mikrokontroler, zewnętrzne czujniki i sygnały elektryczne pochodzące z innego obwodu. [11]

**Możliwość wykorzystania w projekcie:** podręcznik może służyć jako podstawa projektowania bezpiecznego interfejsu sygnału spustu z wykorzystaniem optoizolacji, prawidłowego prowadzenia zasilania 3,3 V i właściwych poziomów logicznych. Nie zastępuje jednak dokumentacji konkretnego optoizolatora ani pomiarów parametrów obwodu repliki. W projektowanej architekturze wskaźnik laserowy pozostaje niezależnym układem elektrycznym.

### 2.12. Montaż prototypu i technika lutowania

Charles Platt w trzecim wydaniu *Make: Electronics* przedstawia praktyczne ćwiczenia z podstaw elektroniki, połączeń elektrycznych i montażu. Oddzielna część książki poświęcona jest lutowaniu, w tym łączeniu przewodów i montażowi elementów. Jest to literatura uzupełniająca o charakterze warsztatowym, a nie źródło wyników badań nad synchronizacją. [12]

**Możliwość wykorzystania w projekcie:** opisane techniki można wykorzystać przy wykonywaniu połączeń między zasilaniem, ESP32-C3, modułem MPU-6050 i układem detekcji spustu. Szczególnie ważne są trwałość połączeń, odpowiednie zabezpieczenie przewodów i eliminowanie przypadkowych przerw kontaktowych podczas ruchu repliki. Zasady montażu warto później odnieść do dokumentacji konstrukcyjnej prototypu.

### 2.13. Projektowanie architektury systemów wbudowanych

Marilyn Wolf w podręczniku *Computers as Components: Principles of Embedded Computing System Design* omawia metody projektowania systemów wbudowanych, uwzględniające współpracę oprogramowania ze sprzętem, organizację zadań, interfejsy wejścia i wyjścia oraz komunikację w systemach IoT. Szczególnie istotne są zagadnienia związane z projektowaniem architektury, analizą wydajności i rozdzielaniem zadań wykonywanych przez urządzenie [13].

**Możliwość wykorzystania w projekcie:** podręcznik stanowi podstawę do podziału obowiązków pomiędzy ESP32-C3 i Raspberry Pi. ESP32-C3 może odpowiadać za cykliczny odczyt IMU, wykrywanie naciśnięcia spustu i nadawanie znaczników czasu, natomiast Raspberry Pi za odbiór danych, rejestrację obrazu i ich późniejsze połączenie. Opisane zasady pomagają również uzasadnić oddzielenie pozyskiwania pomiarów od transmisji sieciowej.

### 2.14. Organizacja zadań i ograniczenia czasowe systemu

Jane W. S. Liu w podręczniku *Real-Time Systems* przedstawia podstawy projektowania systemów czasu rzeczywistego, w tym planowanie zadań okresowych i sporadycznych, analizę czasów odpowiedzi, opóźnienia oraz zjawisko jitteru. Omawia także wpływ harmonogramowania zadań na dotrzymywanie ograniczeń czasowych w systemach komputerowych [14].

**Możliwość wykorzystania w projekcie:** zagadnienia te pozwalają zaplanować obsługę pomiarów IMU oraz zdarzenia spustu tak, aby czynności komunikacyjne nie powodowały nadmiernych opóźnień akwizycji. Pomogą też określić metryki testowe, takie jak odstępy między kolejnymi pomiarami, jitter próbkowania i opóźnienie rejestracji zdarzenia. Ponieważ ESP32-C3 i Raspberry Pi nie tworzą automatycznie systemu o gwarantowanych czasach reakcji, rzeczywiste parametry trzeba sprawdzić eksperymentalnie.

## 3. Wnioski z przeglądu literatury

Analizowane źródła wskazują, że problem komunikacji i synchronizacji powinien zostać rozpatrzony na kilku poziomach. Prace dotyczące protokołów IoT i podstaw sieci komputerowych pomagają porównać narzut transmisji oraz charakterystykę dostarczania niewielkich pakietów danych [1, 2, 6]. Nie rozwiązują jednak samego problemu zgodności czasowej pomiarów. Badania systemów kamera–IMU, przegląd synchronizacji zegarów i specyfikacja NTP uzasadniają stosowanie znaczników czasu, estymacji przesunięcia między zegarami i uwzględniania ich dryftu [3, 4, 5, 7].

Dokumentacja techniczna ESP32-C3, czujnika MPU-6050 oraz biblioteki Picamera2 wyznacza praktyczne możliwości implementacji akwizycji danych [8, 9, 10]. Wstępnie zasadne jest, aby mikrokontroler oznaczał pomiary IMU oraz zdarzenie spustu lokalnym czasem monotonicznym, a Raspberry Pi przechowywało metadane czasowe klatek. Następnie należy estymować relację między zegarami, zidentyfikować braki próbek i połączyć dane na jednej osi czasu. Rozważane rozwiązania powinny zostać ocenione pod względem błędu synchronizacji, dryftu, utraty pakietów i opóźnień skrajnych; ich skuteczności nie można przesądzić bez pomiarów na stanowisku.

Podręczniki dotyczące architektury systemów wbudowanych i systemów czasu rzeczywistego uzupełniają przegląd o zasady podziału zadań oraz analizy ograniczeń czasowych [13, 14]. Podręczniki poświęcone elektronice oraz praktycznemu montażowi uzupełniają część programowo-komunikacyjną o wymagania realizacji fizycznego prototypu [11, 12]. Szczególnie istotne jest poprawne oddzielenie sygnału spustu od wejść mikrokontrolera, prawidłowe zasilanie czujników i trwałość połączeń. W pracy należy przy tym odróżnić zalecenia literaturowe od rozwiązań, które zostaną faktycznie zaimplementowane i zweryfikowane.

## 4. Bibliografia

[1] A. Kirilov, D. Chikurtev, G. Nedeltcheva, P. So, **„Assessing MQTT, CoAP, and HTTP Performance in Real-Life Scenarios on ESP32-Based IoT Nodes”**, *Engineering Proceedings*, vol. 150, nr 1, art. 126, MDPI, 2026. https://doi.org/10.3390/engproc2026150126

[2] P. Levush, A. Luchechko, **„Performance Evaluation of ESP-NOW for Low-Latency Indoor IoT Systems”**, *Advances in Cyber-Physical Systems*, vol. 11, Lviv Polytechnic National University, 2026. https://doi.org/10.23939/acps2026.01.001

[3] F. Malawski, K. Kapela, M. Krupa, **„Synchronization of External Inertial Sensors and Built-in Camera on Mobile Devices”**, *2023 IEEE Symposium Series on Computational Intelligence (SSCI)*, IEEE, 2023. https://doi.org/10.1109/SSCI52147.2023.10371853

[4] M. Li, A. I. Mourikis, **„3-D Motion Estimation and Online Temporal Calibration for Camera-IMU Systems”**, *2013 IEEE International Conference on Robotics and Automation (ICRA)*, IEEE, 2013. https://doi.org/10.1109/ICRA.2013.6631398

[5] B. Sundararaman, U. Buy, A. D. Kshemkalyani, **„Clock Synchronization for Wireless Sensor Networks: A Survey”**, *Ad Hoc Networks*, vol. 3, nr 3, s. 281–323, Elsevier, 2005. https://doi.org/10.1016/j.adhoc.2005.01.002

[6] L. L. Peterson, B. S. Davie, **„Computer Networks: A Systems Approach”**, wyd. 6, Morgan Kaufmann / Elsevier, 2021. https://shop.elsevier.com/books/computer-networks/peterson/978-0-12-818200-0

[7] D. L. Mills, J. Martin, J. Burbank, W. Kasch, **„Network Time Protocol Version 4: Protocol and Algorithms Specification”**, RFC 5905, Internet Engineering Task Force (IETF), 2010. https://www.rfc-editor.org/rfc/rfc5905

[8] Espressif Systems, **„ESP-IDF Programming Guide — ESP32-C3”**, oficjalna dokumentacja techniczna, Espressif Systems, wydanie internetowe aktualizowane (dostęp: 4.11.2026). https://documentation.espressif.com/esp-idf/en/latest/esp32c3/index.html

[9] InvenSense, **„MPU-6000/MPU-6050 Product Specification”**, nr PS-MPU-6000A-00, rev. 3.4, InvenSense, 2013. https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Datasheet.pdf

[10] Raspberry Pi Ltd, **„The Picamera2 Library”**, oficjalny podręcznik biblioteki Picamera2, Raspberry Pi, wydanie internetowe aktualizowane (dostęp: 4.11.2026). https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf

[11] P. Horowitz, W. Hill, **„The Art of Electronics”**, wyd. 3, Cambridge University Press, 2015. https://www.cambridgebookshop.co.uk/products/the-art-of-electronics

[12] C. Platt, **„Make: Electronics”**, wyd. 3, Make: Community / Maker Media, 2021. https://www.oreilly.com/library/view/make-electronics-3rd/9781680456868/

[13] M. Wolf, **„Computers as Components: Principles of Embedded Computing System Design”**, wyd. 4, Morgan Kaufmann / Elsevier, 2016. https://shop.elsevier.com/books/computers-as-components/wolf/978-0-12-805387-4

[14] J. W. S. Liu, **„Real-Time Systems”**, Prentice Hall, 2000. https://books.google.com/books?id=uRlOngEACAAJ
