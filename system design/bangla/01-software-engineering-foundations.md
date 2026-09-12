# অধ্যায় ০১ — Software Engineering-এর ভিত্তি 🟢

> একটামাত্র codebase-এর স্তরে architecture।
> একটা service-এর ভেতরের কোড যদি জলাভূমি হয়, তাহলে ডায়াগ্রামে যত সুন্দর বাক্স আর তীরই আঁকুন না কেন, কিছুই আপনাকে বাঁচাতে পারবে না।

এই অধ্যায়ের তিনটা অংশ:

১. **Code-level architecture** — নীতি (SOLID, DRY, coupling, cohesion)
২. **Design pattern** — ক্লাসিক Gang of Four তালিকা
৩. **Enterprise pattern** — Repository, Unit of Work, CQRS, Domain Event

---

# পর্ব ১ — Code-level architecture 🟢

## ১.১ যে দুটো শব্দ সবকিছু ব্যাখ্যা করে: Coupling আর Cohesion

SOLID-এর আগে, pattern-এর আগে, দুটো শব্দ আছে। এই অধ্যায়ের বাকি সব নীতি এই দুটোরই সেবা করার জন্য।

### Coupling — একটা জিনিস আরেকটার উপর কতটা নির্ভরশীল

**বাস্তব জীবন:** পুরনো আমলের ক্রিসমাস লাইটের কথা ভাবুন। একটা বাল্ব নষ্ট হলে পুরো মালাটা অন্ধকার। এটাই **tight coupling**। আর আধুনিক LED মালা, যেখানে প্রতিটা বাল্ব স্বাধীন — **loose coupling**।

**কোডে:**

```csharp
// TIGHT COUPLING — OrderService SQL Server আর SMTP-র সাথে ঝালাই করা
public class OrderService
{
    public void PlaceOrder(Order order)
    {
        var conn = new SqlConnection("Server=prod-01;Database=Shop;...");
        conn.Open();
        // ... এখানে raw SQL ...

        var smtp = new SmtpClient("smtp.gmail.com");
        smtp.Send(new MailMessage("shop@x.com", order.Email, "Thanks!", "..."));
    }
}
```

সমস্যা কী?

- সত্যিকারের database আর সত্যিকারের mail server ছাড়া আপনি এটা test করতে পারবেন না
- business logic না ছুঁয়ে আপনি PostgreSQL-এ যেতে পারবেন না
- business logic না ছুঁয়ে আপনি SendGrid-এ যেতে পারবেন না
- class-টা *connection string* সম্পর্কে জানে, যেটা তার কাজ নয়

```csharp
// LOOSE COUPLING — product-এর উপর নয়, ধারণার উপর নির্ভরশীল
public class OrderService
{
    private readonly IOrderRepository _orders;
    private readonly INotificationSender _notifier;

    public OrderService(IOrderRepository orders, INotificationSender notifier)
    {
        _orders = orders;
        _notifier = notifier;
    }

    public async Task PlaceOrderAsync(Order order)
    {
        await _orders.SaveAsync(order);
        await _notifier.SendAsync(order.Email, "Thanks!", $"Order {order.Id} received.");
    }
}
```

এখন আপনি SQL Server-এর বদলে Postgres, SMTP-র বদলে SendGrid বসাতে পারবেন, আর fake দিয়ে test করতে পারবেন — **business rule-এ হাত না দিয়েই**।

### Coupling-এর মাত্রা (দিকটা মুখস্থ করুন)

সবচেয়ে খারাপ থেকে সবচেয়ে ভালো:

| স্তর | বর্ণনা | উদাহরণ |
|-------|-------------|---------|
| **Content coupling** (সবচেয়ে খারাপ) | এক module আরেকটার ভেতরে হাত ঢুকিয়ে দেয় | অন্য service-এর database table সরাসরি পড়া |
| **Common coupling** | shared global state | Global mutable singleton, সবাই যে config object বদলায় |
| **Control coupling** | এমন একটা flag পাঠানো যা অন্যটার logic নিয়ন্ত্রণ করে | `Process(data, isRefund: true)` |
| **Stamp coupling** | একটা field লাগলেও পুরো object পাঠানো | `SendEmail(customer)`, অথচ শুধু `customer.Email` লাগত |
| **Data coupling** (ভালো) | শুধু যেটুকু data দরকার সেটুকুই পাঠানো | `SendEmail(string emailAddress)` |
| **Message coupling** (সবচেয়ে ভালো) | event/message দিয়ে যোগাযোগ, সরাসরি কোনো জ্ঞান নেই | `OrderPlaced` publish করা, আর কে শুনছে তা না জানা |

> **আর্কিটেক্টের অনুবাদ:** আপনি এই তালিকায় যত উপরে, কিছু বদলালে তত বেশি জিনিস ভাঙে।

### Afferent আর Efferent coupling (যে শব্দগুলো টুলে দেখা যায়)

- **Afferent coupling (Ca)** = কতগুলো জিনিস **আমার** উপর নির্ভরশীল। বেশি Ca = আমি গুরুত্বপূর্ণ; আমাকে বদলানো বিপজ্জনক।
- **Efferent coupling (Ce)** = **আমি** কতগুলো জিনিসের উপর নির্ভরশীল। বেশি Ce = আমি ভঙ্গুর; অন্যরা আমাকে ভাঙে।
- **Instability (I) = Ce / (Ca + Ce)** — ০ (পাথরের মতো শক্ত) থেকে ১ (খুবই অস্থির) এর মধ্যে

আঙুলের নিয়ম: **স্থিতিশীল জিনিস অস্থির জিনিসের উপর নির্ভর করা উচিত নয়।** আপনার domain model স্থিতিশীল হওয়া উচিত (বেশি Ca, কম Ce)। আপনার controller আর adapter অস্থির হওয়া উচিত (কম Ca, বেশি Ce)। আপনার domain যদি web framework import করে, তাহলে আপনি জিনিসটা উল্টো করে ফেলেছেন।

### Cohesion — একটা module-এর ভেতরের জিনিসগুলো কতটা একসাথে যায়

**বাস্তব জীবন:** রান্নাঘরের একটা ড্রয়ারে ছুরি, কাঁটাচামচ আর চামচ = **high cohesion** (সবই খাওয়ার সরঞ্জাম)। আর একটা ড্রয়ারে কাঁটাচামচ, ব্যাটারি, টেপ, একটা পাসপোর্ট আর একপাটি মোজা = **low cohesion**। কিছু দরকার হলে কোথায় খুঁজবেন আপনি জানেনই না।

```python
# LOW COHESION — এই class পাঁচটা অসম্পর্কিত কাজ করে
class Utils:
    def calculate_tax(self, amount): ...
    def send_email(self, to, body): ...
    def resize_image(self, path): ...
    def parse_csv(self, file): ...
    def validate_passport(self, doc): ...
```

`Utils`, `Helper`, `Common`, `Manager` বা `Shared` নামের যে কোনো কিছু প্রায় সবসময়ই cohesion-এর ব্যর্থতা। এটা একটা জঞ্জালের ড্রয়ার।

```python
# HIGH COHESION — প্রতিটা class-এর অস্তিত্বের একটাই কারণ
class TaxCalculator:
    def calculate(self, amount, region): ...
    def calculate_with_exemptions(self, amount, region, exemptions): ...

class ImageResizer:
    def resize(self, image, width, height): ...
    def thumbnail(self, image): ...
```

### লক্ষ্যটা, এক লাইনে

> **Low coupling, high cohesion.**
> যেসব জিনিস একসাথে বদলায়, সেগুলো একসাথে থাকা উচিত। যেগুলো বদলায় না, সেগুলোর একে অপরের সম্পর্কে জানাই উচিত নয়।

এই অধ্যায়ের বাকি সবকিছুই ওই বাক্যটা অর্জনের কৌশল।

---

## ১.২ SOLID — পাঁচটি নীতি

SOLID হলো পাঁচটা নিয়ম, যা object-oriented কোডকে নমনীয় রাখে। মানুষ এগুলো অতিরিক্ত উদ্ধৃত করে আর কম বোঝে, তাই প্রতিটাকে বাস্তব করে দেখা যাক।

### S — Single Responsibility Principle (SRP)

**প্রচলিত (ভুল) বক্তব্য:** "একটা class-এর শুধু একটা কাজ করা উচিত।"
**সঠিক বক্তব্য:** *"একটা class বদলানোর কারণ একটাই হওয়া উচিত।"* — অথবা আরও ভালো, **"একটাই actor-এর কাছে সে জবাবদিহি করে।"**

**বাস্তব জীবন:** একটা রেস্তোরাঁ। শেফ রান্না করেন। ওয়েটার পরিবেশন করেন। ক্যাশিয়ার টাকা নেন। একজন মানুষ যদি তিনটাই করতেন, তাহলে মেনুর পরিবর্তন, বসার নকশার পরিবর্তন, *আর* ট্যাক্স আইনের পরিবর্তন — সবই একই মানুষকে বিরক্ত করত।

```csharp
// লঙ্ঘন — এই class তিনটা আলাদা বিভাগের কাছে জবাবদিহি করে
public class Employee
{
    public decimal CalculatePay()  { ... }   // FINANCE নিয়ম বদলালে বদলায়
    public void SaveToDatabase()   { ... }   // DBA/IT storage বদলালে বদলায়
    public string ReportHours()    { ... }   // HR report ফরম্যাট বদলালে বদলায়
}
```

তিনজন actor (Finance, IT, HR) → বদলানোর তিনটা কারণ → এটা অনবরত সম্পাদিত হবে, এমন মানুষদের হাতে যারা একে অপরের অংশ বোঝে না, আর তারা একে অপরের জিনিস ভাঙবে।

```csharp
// ঠিক করা
public class Employee { /* শুধু data + domain rule */ }
public class PayCalculator     { public decimal Calculate(Employee e) { ... } }
public class EmployeeRepository{ public void Save(Employee e)        { ... } }
public class HourReporter      { public string Report(Employee e)    { ... } }
```

**লঙ্ঘন কীভাবে চিনবেন:**
- class-এর নামে "And" আছে, বা থাকতে পারত
- `Manager`/`Processor`/`Handler` শব্দটা আর ৯০০ লাইন কোড
- আলাদা আলাদা টিম অসম্পর্কিত কারণে একই ফাইলে বারবার হাত দিচ্ছে
- একটা test ফাইলে ১২টা আলাদা mock লাগছে

**অতিরিক্ত করবেন না।** SRP চরমে নিয়ে গেলে আপনি ৪০০টা এক-method-এর class পাবেন আর কেউ কিছু খুঁজে পাবে না। মাপার একক হলো **actor/বদলানোর কারণ**, method-এর সংখ্যা নয়।

### O — Open/Closed Principle (OCP)

*"Software entity গুলো extension-এর জন্য খোলা থাকবে, কিন্তু modification-এর জন্য বন্ধ।"*

সহজ ভাষায়: **বিদ্যমান, পরীক্ষিত কোড সম্পাদনা না করেই আপনার নতুন আচরণ যোগ করতে পারা উচিত।**

**বাস্তব জীবন:** একটা বৈদ্যুতিক সকেট। নতুন ডিভাইস যোগ করতে আপনি বাড়ির তার নতুন করে টানেন না — আপনি প্লাগ লাগান। সকেটটা *বন্ধ* (আপনি একে বদলান না), আর *খোলা* (যে কোনো ডিভাইস একে বাড়াতে পারে)।

```python
# লঙ্ঘন — প্রতিটা নতুন payment method মানে এই function সম্পাদনা করা
def process_payment(payment_type, amount):
    if payment_type == "card":
        # ৩০ লাইন
    elif payment_type == "bkash":
        # ৩০ লাইন
    elif payment_type == "paypal":
        # ৩০ লাইন
    # পরের মাসে: elif "nagad" ... আর আপনি সবকিছু আবার test করবেন
```

```python
# ঠিক করা — Strategy pattern
from abc import ABC, abstractmethod

class PaymentMethod(ABC):
    @abstractmethod
    def pay(self, amount: Money) -> PaymentResult: ...

class CardPayment(PaymentMethod):
    def pay(self, amount): ...

class BkashPayment(PaymentMethod):
    def pay(self, amount): ...

class NagadPayment(PaymentMethod):   # নতুন ফাইল। আর কিছুই বদলায়নি।
    def pay(self, amount): ...

class PaymentProcessor:
    def __init__(self, methods: dict[str, PaymentMethod]):
        self._methods = methods

    def process(self, method_key: str, amount: Money) -> PaymentResult:
        return self._methods[method_key].pay(amount)
```

**সৎ সতর্কবার্তা:** আপনি সবকিছুকে extension-এর জন্য খোলা বানাতে পারবেন না। আপনি abstraction-এ ডুবে যাবেন। OCP প্রয়োগ করুন সেখানে যেখানে আপনার কাছে *প্রমাণ* আছে যে বৈচিত্র্য ঘটে — payment method, notification channel, ট্যাক্সের নিয়ম, document type, file format। একই `if/elif` চেইন আপনি যদি দুইবার সম্পাদনা করে থাকেন, সেটাই আপনার প্রমাণ।

### L — Liskov Substitution Principle (LSP)

*"S যদি T-এর subtype হয়, তাহলে T type-এর object-এর জায়গায় S type-এর object বসালে প্রোগ্রাম ভাঙবে না।"*

সহজ ভাষায়: **parent-এর জায়গায় child class ব্যবহার করা যাবে, কোনো চমক ছাড়াই।**

**বাস্তব জীবন:** একটা "কফি মেশিন", যেটাতে *brew* চাপলে কফির বদলে একটা ইমেইল পাঠায়। কারিগরিভাবে এটা interface-টা implement করে। কিন্তু এটা বদলি হিসেবে চলে না।

ক্লাসিক উদাহরণ:

```csharp
public class Rectangle
{
    public virtual int Width  { get; set; }
    public virtual int Height { get; set; }
    public int Area => Width * Height;
}

public class Square : Rectangle   // "একটা বর্গক্ষেত্র একটা আয়তক্ষেত্রই" — গাণিতিকভাবে সত্য
{
    public override int Width  { set { base.Width = base.Height = value; } }
    public override int Height { set { base.Width = base.Height = value; } }
}

// Rectangle-এর বিপরীতে লেখা caller:
void Test(Rectangle r)
{
    r.Width = 5;
    r.Height = 4;
    Assert.Equal(20, r.Area);   // Rectangle-এ PASS, Square-এ FAIL (১৬)
}
```

কোডটা compile হয়। Logic নীরবে ভুল। **Inheritance বাস্তব জগতের "is-a" সম্পর্ক মডেল করেছে, কিন্তু প্রোগ্রামের আচরণ ভেঙে দিয়েছে।**

**বাস্তব সিস্টেমে সাধারণ LSP লঙ্ঘন:**

```python
class Bird:
    def fly(self): ...

class Penguin(Bird):
    def fly(self):
        raise NotImplementedError("Penguins can't fly")  # LSP লঙ্ঘন
```

```csharp
// একটা read-only collection যেটা Add()-এ throw করে, অথচ IList<T> সাজে
public class ReadOnlyList<T> : IList<T>
{
    public void Add(T item) => throw new NotSupportedException(); // লঙ্ঘন
}
```

**LSP মানতে হলে:**
- Subclass **precondition শক্ত করতে পারবে না** (parent-এর চেয়ে বেশি কিছু দাবি করতে পারবে না)
- Subclass **postcondition দুর্বল করতে পারবে না** (parent-এর চেয়ে কম প্রতিশ্রুতি দিতে পারবে না)
- Subclass এমন **নতুন exception type ছুঁড়তে পারবে না** যা caller আশা করে না
- Parent-এর invariant গুলো এখনো সত্য থাকতে হবে

**ব্যবহারিক নিয়ম:** caller-এ যদি `if (x is SubType)` লাগে, তাহলে LSP ইতিমধ্যেই ভেঙে গেছে। আর সন্দেহ হলে **inheritance-এর চেয়ে composition-কে প্রাধান্য দিন** (১.৬ দেখুন)।

### I — Interface Segregation Principle (ISP)

*"কোনো client-কে এমন method-এর উপর নির্ভর করতে বাধ্য করা উচিত নয় যেগুলো সে ব্যবহার করে না।"*

**বাস্তব জীবন:** একটা TV রিমোটে ৬০টা বোতাম, অথচ আপনি ব্যবহার করেন মাত্র ৪টা। আরও খারাপ: প্রস্তুতকারক যতবার একটা বোতাম যোগ করে, আপনাকে নতুন রিমোট কিনতে হয়।

```csharp
// লঙ্ঘন — একটা মোটা interface
public interface IWorker
{
    void Work();
    void Eat();
    void Sleep();
    void AttendMeeting();
    void SubmitTimesheet();
}

public class RobotWorker : IWorker
{
    public void Work() { ... }
    public void Eat()   => throw new NotSupportedException();  // দুর্গন্ধ
    public void Sleep() => throw new NotSupportedException();  // দুর্গন্ধ
    // ...
}
```

```csharp
// ঠিক করা — ছোট, ভূমিকা-ভিত্তিক interface
public interface IWorkable      { void Work(); }
public interface IFeedable      { void Eat(); }
public interface IReportable    { void SubmitTimesheet(); }

public class HumanWorker : IWorkable, IFeedable, IReportable { ... }
public class RobotWorker : IWorkable { ... }
```

**বাস্তব ISP-র জয়:** একটা liveness/KYC সিস্টেমে ১৫টা method সহ একটা `IVerificationVendor` বানাবেন না (`DetectFace`, `MatchFace`, `ReadPassportMRZ`, `CheckSanctionsList`, `EstimateAge`, …)। কোনো ভেন্ডরই ১৫টা implement করে না। বানান `IFaceDetector`, `IFaceMatcher`, `IDocumentReader`, `ISanctionsScreener` — তারপর প্রতিটা ক্ষমতার জন্য যে ভেন্ডর ব্যবহার করেন সেগুলো compose করুন। আপনি যখন document ভেন্ডর বদলাবেন, face-এর কোড নড়বে না।

### D — Dependency Inversion Principle (DIP)

*"High-level module গুলো low-level module-এর উপর নির্ভর করবে না। দুটোই abstraction-এর উপর নির্ভর করবে। Abstraction detail-এর উপর নির্ভর করবে না; detail abstraction-এর উপর নির্ভর করবে।"*

এটাই architecture-এর দিক থেকে সবচেয়ে গুরুত্বপূর্ণ অক্ষরটা। Hexagonal, Onion আর Clean Architecture-এর ভিত্তি এটাই (অধ্যায় ০২)।

**বাস্তব জীবন:** একটা বাতির তার সরাসরি বিদ্যুৎকেন্দ্রে ঝালাই করা থাকে না। বাতি আর বিদ্যুৎব্যবস্থা দুটোই একটা **abstraction**-এ একমত — প্লাগ আর সকেটের মান। দুই পক্ষই স্বাধীনভাবে বদলাতে পারে।

```
DIP ছাড়া (dependency নিয়ন্ত্রণপ্রবাহ অনুসরণ করে — খারাপ)

   [ Business Logic ]
           │ নির্ভর করে
           ▼
   [ SqlServerRepository ]          ← business logic SQL Server সম্পর্কে জানে


DIP সহ (dependency উল্টে গেছে — ভালো)

   [ Business Logic ]
           │ নির্ভর করে
           ▼
   [ IOrderRepository ]  ◄────── implement করে ────── [ SqlServerRepository ]

   তীরের দিকটা খেয়াল করুন: DETAIL তাকিয়ে আছে ABSTRACTION-এর দিকে।
```

**যে সূক্ষ্ম ব্যাপারটা বেশিরভাগ মানুষ ভুল করে:** interface-টা **high-level module**-এর, low-level-এর নয়। `IOrderRepository` থাকবে আপনার *domain/application* প্রজেক্টে, *infrastructure* প্রজেক্টে নয়। এটাই একে inversion বানায়। আপনি যদি interface-টা SQL implementation-এর পাশে রাখেন, তাহলে আপনি শুধু একটা অকেজো indirection-এর স্তর যোগ করলেন, কিছুই উল্টালেন না।

```
MyApp.Domain/
    Order.cs
    IOrderRepository.cs          ← interface থাকবে এখানে (business-এর সাথে)
MyApp.Infrastructure/
    SqlOrderRepository.cs        ← implementation থাকবে এখানে, আর Domain-কে reference করবে
```

Build-এর সময় dependency-র তীর এখন **ভেতরের দিকে**, business-এর দিকে তাকিয়ে আছে। আপনি পুরো Infrastructure প্রজেক্ট মুছে ফেললেও Domain compile হবে। এটাই পরীক্ষা।

### SOLID সারসংক্ষেপ কার্ড

| অক্ষর | এক লাইন | যে দুর্গন্ধ দূর করে |
|--------|----------|----------------|
| **S** | বদলানোর একটাই কারণ | God class, `Utils` |
| **O** | সম্পাদনা ছাড়াই বাড়ানো | ক্রমবর্ধমান `if/elif` চেইন |
| **L** | Subtype চমক দেবে না | `NotImplementedException`, `is SubType` চেক |
| **I** | ছোট, ভূমিকা-ভিত্তিক interface | মোটা interface, অব্যবহৃত method |
| **D** | নিজের মালিকানার abstraction-এর উপর নির্ভর করা | Business logic SDK আর driver import করছে |

---

## ১.৩ DRY — Don't Repeat Yourself

*"প্রতিটা জ্ঞানের টুকরোর একটা সিস্টেমের ভেতরে একটাই, দ্ব্যর্থহীন, প্রামাণিক রূপ থাকতে হবে।"*

**জ্ঞান** শব্দটা খেয়াল করুন। DRY দেখতে-একরকম টেক্সট নিয়ে **নয়**।

```csharp
// এগুলো দেখতে একই রকম। এগুলো duplication নয়।
public bool IsEligibleForDiscount(Customer c) => c.Age > 60;
public bool CanAccessSeniorLounge(Customer c) => c.Age > 60;
```

দুটো আলাদা business rule, যাদের সীমা আজ একই। আপনি যদি এদের "DRY" করে `IsOver60()` বানান, তাহলে যেদিন marketing ছাড়ের বয়স ৫৫ করবে কিন্তু lounge ৬০-এই থাকবে, সেদিন আপনি একটা bug আর একটা বিশ্রী refactor পাবেন।

### বিপদ: ভুল abstraction duplication-এর চেয়ে খারাপ

> **"Duplication ভুল abstraction-এর চেয়ে অনেক সস্তা।"** — Sandi Metz

ব্যর্থতার ধারাটা এত সাধারণ যে এর একটা আকৃতিই আছে:

১. দুই টুকরো একই রকম কোড দেখা গেল
২. কেউ একটা shared function বের করল
৩. নতুন একটা requirement case A-কে একটু আলাদা করল → একটা boolean parameter যোগ
৪. আরেকটা পার্থক্য → আরেকটা parameter
৫. ছয় মাস পর: `process(data, isRefund, skipTax, legacyMode, forCorporate, dryRun)`
৬. কেউ নিরাপদে এটা বদলাতে পারে না; সবাই এটাকে ভয় পায়

**ব্যবহারিক নিয়ম (Rule of Three):** দ্বিতীয়বার দেখলেই abstract করবেন না। তৃতীয়বারের জন্য অপেক্ষা করুন। ততক্ষণে আপনি আসল abstraction-এর *আকৃতি* দেখতে পাবেন।

### DRY কোথায় সবচেয়ে জরুরি (আসল জ্ঞানের পুনরাবৃত্তি)

- **Business rule** — VAT-এর হার, retry limit, password policy, fraud-এর সীমা
- **Validation rule** — frontend আর backend-এ একই validation *গ্রহণযোগ্য* duplication (কারণ আলাদা: UX বনাম security), তবে যেখানে সম্ভব একটা উৎস থেকে তৈরি হওয়া উচিত (shared schema/contract)
- **Configuration** — ৫টা config ফাইলে একটা URL
- **Database schema-র জ্ঞান** — table-এর গঠন একটা mapping/model-এর বদলে ১০ জায়গায় hard-code করা
- **API contract** — হাতে লেখার বদলে OpenAPI/proto থেকে client generate করা

### WET, AHA আর আধুনিক দৃষ্টিভঙ্গি

- **WET** = "Write Everything Twice" (DRY-এর মজার পাল্টা)
- **AHA** = "Avoid Hasty Abstractions" — সবচেয়ে ভালো আধুনিক পরামর্শ। *ভুল abstraction-এর চেয়ে duplication ভালো; কম লাইনের জন্য নয়, পরিবর্তনের জন্য optimise করুন।*

---

## ১.৪ KISS আর YAGNI

### KISS — Keep It Simple, Stupid

যে সবচেয়ে সহজ সমাধান সমস্যাটা পুরোপুরি সমাধান করে, সেটাই সাধারণত সঠিক।

**বাস্তব উদাহরণ।** একটা টিমের দিনে একবার একটা task চালাতে হতো।

- **তারা যা বানাল:** Kafka topic + scheduler service + Redis-এ একটা state machine + একটা retry orchestrator + নিজেদের লেখা একটা Kubernetes CronJob controller। ছয় সপ্তাহ।
- **যা দরকার ছিল:** একটা cron entry যেটা একটা script চালায়, সাথে Postgres-এ একটা lock row যাতে দুটো instance সংঘর্ষ না করে। এক বিকেল।

প্রথম টিম মজা পেয়েছিল। দ্বিতীয় টিম product ship করেছিল।

**সরলতার পরীক্ষা:** *একজন নতুন ডেভেলপার কি এটা ১৫ মিনিটে বুঝতে পারবেন?* না পারলে জটিলতাটার পক্ষে স্পষ্ট যুক্তি দিন — অথবা সরিয়ে ফেলুন।

সাবধান: *simple* ≠ *easy* আর *simple* ≠ *কম লাইন*। Rich Hickey-র পার্থক্যটা জানা মূল্যবান: **simple = জট পাকানো নয়** (কম ধারণা, পরিষ্কারভাবে আলাদা)। **Easy = পরিচিত/হাতের কাছে**। একটা চতুর one-liner প্রায়ই লিখতে easy আর বুঝতে complex। লক্ষ্য রাখুন *simple*-এর দিকে।

### YAGNI — You Aren't Gonna Need It

যে requirement এখনো নেই, তার জন্য বানাবেন না।

```csharp
// YAGNI লঙ্ঘন — আমরা একটা মুদ্রা সাপোর্ট করি; কেউ এগুলো চায়নি
public interface ICurrencyConverter { ... }
public class MultiCurrencyPricingEngine { ... }
public class ExchangeRateProviderFactory { ... }
public class HistoricalRateCache { ... }
```

দুই বছর পর কোম্পানি এখনো একটা দেশেই আছে, আর একটা দাম বদলাতে প্রতিটা ডেভেলপারকে ওই চারটা class পড়তে হয়।

**অনুমানভিত্তিক সাধারণীকরণের খরচ:**
১. আপনি ভুল জিনিস বানান (আপনি ভবিষ্যৎ অনুমান করলেন, আর ভুল করলেন)
২. আপনি চিরকাল এর maintenance দেন
৩. আপনি কোডের প্রতিটা পাঠককে ধীর করে দেন
৪. আসল requirement যখন শেষমেশ আসে, সেটা আপনার অনুমানের সাথে মেলেই না

### কিন্তু YAGNI-র সীমা আছে — যেখানে আপনাকে আগেই ভাবতেই হবে

YAGNI প্রযোজ্য **feature**-এর ক্ষেত্রে, **যে architecture বদলানো ব্যয়বহুল** তার ক্ষেত্রে নয় (অধ্যায় ০০)।

| YAGNI প্রয়োগ করুন | YAGNI প্রয়োগ করবেন না |
|----------------|--------------------|
| Multi-currency, multi-tenant, plugin system | Security — পরে জুড়ে দিলে সেটা সবসময়ই ভাঙা |
| Configurable workflow engine | Primary key-র কৌশল |
| "আমরা হয়তো পরে GraphQL সাপোর্ট করব" | Data model আর entity-র সম্পর্ক |
| "ভবিষ্যতের scale-এর জন্য" বাড়তি microservice | আপনি regulated হলে audit logging |
| এমন caching layer যার দরকার কেউ মাপেনি | PII কোথায় থাকে (এটা ছড়ায়, আর ছড়ানো ফেরানো যায় না) |
| ২টা database-এর উপর abstraction, যার ১টা ব্যবহার করেন | মৌলিক observability (log/metric/trace hook) |

> বিভাজন রেখাটা অধ্যায় ০০-এর সংজ্ঞা: **পরে যোগ করা সস্তা হলে YAGNI করুন। পরে বসানো ব্যয়বহুল হলে এখনই করুন।**

---

## ১.৫ Separation of Concerns

একটা **concern** হলো একটা আগ্রহের ক্ষেত্র: persistence, validation, business rule, presentation, logging, security।

**বাস্তব জীবন:** একটা হাসপাতাল। অভ্যর্থনা, রোগনির্ণয়, অস্ত্রোপচার, ওষুধ, বিলিং। প্রতিটাই একটা concern, নিজস্ব বিশেষজ্ঞ আর নিজস্ব ঘর সহ। আপনি চান না যে সার্জন অপারেশনের মাঝখানে বীমার কাগজপত্রও সামলান।

```python
# সবকিছু মেশানো — বাস্তব জীবনে কোডের সবচেয়ে সাধারণ আকৃতি এটাই
@app.post("/verify")
def verify(request):
    # presentation
    data = request.json
    # validation
    if not data.get("video"):
        return {"error": "video required"}, 400
    # business rule
    if len(data["video"]) > 5_000_000:
        return {"error": "too big"}, 400
    # persistence
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("INSERT INTO sessions (...) VALUES (...)")
    # integration
    r = requests.post("https://vendor.ai/detect", files={"v": data["video"]})
    # আবার business rule
    score = r.json()["score"]
    passed = score > 0.85          # <-- আসল product, ১৬ নম্বর লাইনে চাপা পড়ে আছে
    # আবার persistence
    cur.execute("UPDATE sessions SET score=%s, passed=%s", (score, passed))
    conn.commit()
    # presentation
    return {"passed": passed, "score": score}
```

ওই শেষ function-টা একটা database, একটা ভেন্ডর account আর একটা HTTP server ছাড়া test করা যায় না। আর যে একটা লাইন আসলে আপনার product (`score > 0.85`), সেটা অদৃশ্য।

```python
# আলাদা করা
# --- presentation layer (পাতলা!) ---
@app.post("/verify")
async def verify(req: VerifyRequest, svc: VerificationService = Depends()):
    result = await svc.verify(req.session_id, req.video)
    return VerifyResponse.from_domain(result)

# --- application layer: শুধু orchestration ---
class VerificationService:
    def __init__(self, detector: FaceDetector, repo: SessionRepository):
        self._detector = detector
        self._repo = repo

    async def verify(self, session_id: SessionId, video: VideoData) -> Verification:
        session = await self._repo.get(session_id)
        signals = await self._detector.analyse(video)
        session.record_attempt(signals)      # <-- domain ঠিক করে pass/fail
        await self._repo.save(session)
        return session.latest_result()

# --- domain layer: আসল product, কোনো I/O নেই, বিশুদ্ধ আর testable ---
class LivenessSession:
    PASS_THRESHOLD = 0.85
    MAX_ATTEMPTS = 3

    def record_attempt(self, signals: Signals) -> None:
        if self._attempts >= self.MAX_ATTEMPTS:
            raise TooManyAttempts(self.id)
        passed = signals.liveness_score > self.PASS_THRESHOLD and not signals.spoof_detected
        self._results.append(Result(signals, passed))
        self._attempts += 1
```

এখন business rule একটা ছোট class, যেটা আপনি কোনো infrastructure ছাড়াই মাইক্রোসেকেন্ডে unit-test করতে পারেন। **এটাই লাভ।**

### Cross-cutting concern

কিছু concern *প্রতিটা* স্তরকে কেটে যায়: logging, authentication, authorisation, caching, transaction, retry, metric, validation।

আপনি যদি এগুলো প্রতিটা method-এ পেস্ট করেন, তাহলে শুধু গোলমাল পাবেন। এগুলোকে business কোডের বাইরে রাখার কৌশল:

- **Middleware / filter / pipeline behaviour** (ASP.NET middleware, FastAPI dependency, MediatR behaviour)
- **Decorator** (একটা service-কে logging বা caching decorator দিয়ে মুড়ে দিন — ১.৮ দেখুন)
- **Aspect-Oriented Programming (AOP)** — interceptor, attribute (`[Authorize]`, `[Transactional]`)
- **Sidecar / service mesh** — একদম process-এর *বাইরে* করুন (অধ্যায় ১৫)

```csharp
// MediatR pipeline behaviour — প্রতিটা command-এ logging, একবার লেখা
public class LoggingBehaviour<TReq, TRes> : IPipelineBehavior<TReq, TRes>
    where TReq : notnull
{
    private readonly ILogger<LoggingBehaviour<TReq, TRes>> _log;
    public LoggingBehaviour(ILogger<LoggingBehaviour<TReq, TRes>> log) => _log = log;

    public async Task<TRes> Handle(TReq request, RequestHandlerDelegate<TRes> next,
                                   CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();
        _log.LogInformation("Handling {Request}", typeof(TReq).Name);
        var response = await next();
        _log.LogInformation("Handled {Request} in {Ms}ms", typeof(TReq).Name, sw.ElapsedMilliseconds);
        return response;
    }
}
```

---

## ১.৬ Inheritance-এর চেয়ে Composition

**Inheritance** = "is-a" (এটা একটা …)। **Composition** = "has-a" (এর একটা … আছে)।

### Inheritance কেন হতাশ করে

১. **এটাই সবচেয়ে শক্ত coupling।** Subclass parent-এর *implementation*-এর উপর নির্ভর করে, শুধু interface-এর উপর নয়। Parent বদলান, আর এমন child ভাঙবে যেগুলো আপনি কখনো পড়েনওনি। (এটাই "fragile base class" সমস্যা।)
২. **বেশিরভাগ ভাষায় এটা একক আর স্থায়ী।** একটাই parent, compile-এর সময় বাছা, চিরকালের জন্য।
৩. **গভীর hierarchy পড়া যায় না।** `PremiumCorporateDiscountedOrder` বুঝতে আপনাকে উপরের দিকে পাঁচটা ফাইল পড়তে হবে।
৪. **সংমিশ্রণের বিস্ফোরণ।** দুটো স্বাধীন বৈচিত্র্য যোগ করলে চারটা class লাগে; তৃতীয়টা যোগ করলে আটটা।

ক্লাসিক বিপর্যয়:

```
                Employee
               /        \
      FullTime            Contractor
       /     \             /      \
  Salaried  Hourly    Remote    OnSite
     /  \
Manager  IC
  ...এবার "part-time remote hourly manager" যোগ করুন। পারবেন না।
```

```csharp
// COMPOSITION — প্রতিটা বৈচিত্র্য একটা স্বাধীন, বদলানো যায় এমন অংশ
public class Employee
{
    private readonly IPaymentPolicy _payment;    // salaried / hourly / commission
    private readonly IWorkLocation  _location;   // remote / office / hybrid
    private readonly ILeavePolicy   _leave;      // full-time / part-time / contract

    public Employee(IPaymentPolicy payment, IWorkLocation location, ILeavePolicy leave)
        => (_payment, _location, _leave) = (payment, location, leave);

    public Money CalculatePay(Period p) => _payment.Calculate(this, p);
}

// এখন যে কোনো সংমিশ্রণ সম্ভব, এমনকি যেগুলো আপনি ভাবেনওনি:
var weirdButValid = new Employee(new HourlyPayment(), new Remote(), new ContractLeave());
```

### কখন inheritance-ই সঠিক

গোঁড়া হয়ে যাবেন না। Inheritance সঠিক যখন:

- সম্পর্কটা সত্যিই **is-a** আর স্থায়ী (`SqlException : Exception`)
- আপনি একটা **framework-এর extension point** বানাচ্ছেন (`class MyController : ControllerBase`)
- **Template Method** pattern — একটা নির্দিষ্ট algorithm, বদলানো যায় এমন ধাপ সহ (১.৯ দেখুন)
- Hierarchy **অগভীর** (১–২ স্তর) আর **স্থিতিশীল**

> **নিয়ম:** *পরিচয় আর interface*-এর জন্য inherit করুন। *আচরণ আর বৈচিত্র্য*-এর জন্য compose করুন।

---

## ১.৭ Immutability (অপরিবর্তনীয়তা)

একটা **immutable** object তৈরি হওয়ার পর আর বদলানো যায় না। একে "বদলাতে" হলে আপনি নতুন একটা বানান।

**বাস্তব জীবন:** একটা ছাপানো ব্যাংক স্টেটমেন্ট। আপনি গত মাসের স্টেটমেন্ট সম্পাদনা করতে পারবেন না; আপনি নতুন একটা পাবেন। এই কারণেই এটা প্রমাণ হিসেবে বিশ্বাসযোগ্য।

```csharp
// MUTABLE — বিপজ্জনক
public class Money
{
    public decimal Amount { get; set; }
    public string Currency { get; set; }
}

var price = new Money { Amount = 100, Currency = "USD" };
ApplyDiscount(price);      // এটা কি আমার object বদলে দিল? জানতে হলে method পড়তে হবে।
Console.WriteLine(price.Amount);  // ...৫০? ১০০? কে জানে।
```

```csharp
// IMMUTABLE — C# record, positional, ভেতরে value equality সহ
public record Money(decimal Amount, string Currency)
{
    public Money Add(Money other)
    {
        if (other.Currency != Currency)
            throw new InvalidOperationException("Currency mismatch");
        return new Money(Amount + other.Amount, Currency);
    }

    public Money ApplyDiscount(decimal percent) =>
        this with { Amount = Amount * (1 - percent / 100) };
}

var price = new Money(100, "USD");
var discounted = price.ApplyDiscount(20);   // price এখনো ১০০। নিশ্চিত।
```

```python
# Python-এ একই জিনিস
from dataclasses import dataclass, replace
from decimal import Decimal

@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def apply_discount(self, percent: Decimal) -> "Money":
        return replace(self, amount=self.amount * (1 - percent / 100))
```

### আর্কিটেক্টরা immutability নিয়ে কেন মাথা ঘামান

| সুবিধা | Scale-এ কেন গুরুত্বপূর্ণ |
|---------|------------------------|
| **বিনামূল্যে thread-safe** | কোনো lock লাগে না। Concurrent server-এ এটা বিশাল ব্যাপার। |
| **Cache করা নিরাপদ** | Cache-এ রাখা immutable object কোনো caller নষ্ট করতে পারে না |
| **সীমানা পেরিয়ে shared করা নিরাপদ** | যেখানে খুশি পাঠান; কেউ আপনার কপি বদলাতে পারবে না |
| **ভাবতে সহজ** | আপনি যে মান পড়ছেন, সেটাই সেখানে ছিল। কোনো "দূর থেকে ক্রিয়া" bug নেই। |
| **Event-এর জন্য স্বাভাবিক** | একটা event হলো অতীতের একটা সত্য। সত্য বদলায় না। (অধ্যায় ০৬) |
| **সময়ভ্রমণ / audit সম্ভব করে** | প্রতিটা সংস্করণ রাখুন; ইতিহাস বিনামূল্যে পাবেন |

### খরচ

- বেশি object allocation (সাধারণত অপ্রাসঙ্গিক; চিন্তার আগে মাপুন)
- সত্যিকারের বড় mutable কাঠামোর জন্য অসুবিধাজনক (১০ MB-র একটা image buffer — প্রতি pixel-এ কপি করবেন না)
- কিছু ORM আর framework আপনার সাথে লড়ে

**ব্যবহারিক নির্দেশনা:** **Value Object** (Money, Email, DateRange, Coordinates, Score) *সবসময়* immutable বানান। **Entity** (Order, Customer) mutable বানান কিন্তু **নিয়ন্ত্রিত** পরিবর্তন সহ — কোনো public setter নয়, শুধু অর্থপূর্ণ method (`order.Cancel(reason)`, `order.Status = "cancelled"` নয়)। **DTO আর event** immutable বানান।

---

# পর্ব ২ — Design Pattern 🟢

একটা design pattern হলো **একটা বারবার আসা সমস্যার নামযুক্ত, পুনর্ব্যবহারযোগ্য সমাধান**। এগুলোর সবচেয়ে বড় মূল্য কোড নয় — **সাধারণ পরিভাষা**। "চলো ওখানে একটা Adapter বসাই" বললে দশ মিনিটের ব্যাখ্যা বেঁচে যায়।

> **সতর্কতা:** Pattern *আবিষ্কার* করা হয়, *প্রয়োগ* করা হয় না। Pattern বেছে নিয়ে প্রজেক্ট শুরু করবেন না। সহজ জিনিসটা লিখুন; ব্যথা দেখা দিলে আপনি চিনতে পারবেন কোন pattern সেটা কমায়।

## ১.৮ Creational pattern — *object কীভাবে তৈরি হয়*

### Factory Method

**সমস্যা:** যে কোড call করছে, তার জানা উচিত নয় কোন concrete class বানাতে হবে।

```python
class DocumentReader(ABC):
    @abstractmethod
    def extract(self, image: bytes) -> IdentityData: ...

class PassportReader(DocumentReader): ...
class NationalIdReader(DocumentReader): ...
class DrivingLicenceReader(DocumentReader): ...

class DocumentReaderFactory:
    _readers = {
        DocType.PASSPORT: PassportReader,
        DocType.NID:      NationalIdReader,
        DocType.LICENCE:  DrivingLicenceReader,
    }

    @classmethod
    def create(cls, doc_type: DocType) -> DocumentReader:
        try:
            return cls._readers[doc_type]()
        except KeyError:
            raise UnsupportedDocumentType(doc_type)

# Caller concrete reader সম্পর্কে কিছুই জানে না:
reader = DocumentReaderFactory.create(request.doc_type)
data = reader.extract(image)
```

**ব্যবহার করুন যখন:** concrete type রানটাইমের input-এর উপর নির্ভর করে (config, ব্যবহারকারীর পছন্দ, tenant, দেশ)।

### Abstract Factory

**সমস্যা:** আপনার সম্পর্কিত object-এর **পরিবার** বানাতে হবে, যেগুলো একে অপরের সাথে মিলতে হবে।

```csharp
// একটা পুরো ভেন্ডর "পরিবার": Vendor A-র detector ব্যবহার করলে A-রই matcher লাগবে
public interface IBiometricVendorFactory
{
    IFaceDetector   CreateDetector();
    IFaceMatcher    CreateMatcher();
    ILivenessScorer CreateScorer();
}

public class AwsRekognitionFactory : IBiometricVendorFactory { ... }
public class AzureFaceFactory      : IBiometricVendorFactory { ... }
public class OnPremiseFactory      : IBiometricVendorFactory { ... }

// এক লাইন configuration দিয়ে পুরো পরিবার বদলে ফেলুন:
IBiometricVendorFactory factory = config.Vendor switch
{
    "aws"   => new AwsRekognitionFactory(),
    "azure" => new AzureFaceFactory(),
    _       => new OnPremiseFactory()
};
```

**ব্যবহার করুন যখন:** পরিবারগুলোর মধ্যে component মেশালে সেটা একটা bug হবে। বিরল, কিন্তু যেখানে মানায় সেখানে মূল্যবান (cross-cloud, on-prem বনাম SaaS, multi-region compliance)।

### Builder

**সমস্যা:** অনেক optional parameter সহ একটা object। Constructor বিস্ফোরিত হয়।

```csharp
// রোগ: telescoping constructor
new Report(data, true, false, null, 10, "USD", null, true, false);  // মানে কী?!
```

```csharp
// ওষুধ
var report = new ReportBuilder()
    .ForPeriod(startDate, endDate)
    .InCurrency("USD")
    .GroupedBy(GroupBy.Month)
    .IncludingFailedVerifications()
    .WithPageSize(50)
    .Build();
```

Builder আপনাকে **`Build()`-এ validate করার** সুযোগও দেয় ("আপনাকে হয় একটা period নয় একটা customer দিতে হবে") আর একটা immutable object ফেরত দিতে দেয়।

**ব্যবহার করুন যখন:** ৪+ constructor parameter, অনেকগুলো optional; অথবা ধাপে ধাপে নির্মাণ দরকার; অথবা তৈরি object-টা immutable হওয়া উচিত।

### Singleton

**সমস্যা:** ঠিক একটাই instance থাকতে হবে (একটা connection pool, একটা config registry, একটা metrics collector)।

```csharp
public sealed class ConfigStore
{
    private static readonly Lazy<ConfigStore> _instance = new(() => new ConfigStore());
    public static ConfigStore Instance => _instance.Value;
    private ConfigStore() { }
}
```

**⚠️ Singleton সফটওয়্যারের সবচেয়ে অপব্যবহৃত pattern।** সমস্যাগুলো:

- এটা **global mutable state**, স্যুট পরে বসে আছে
- এটা testing কঠিন করে (আপনি একে বদলাতে পারবেন না; test গুলো একে অপরের ভেতর state ফাঁস করে)
- এটা dependency লুকায় — `ConfigStore.Instance` ব্যবহার করা class ঘোষণা করে না যে তার config লাগে
- Distributed system-এ "শুধু একটা instance" এমনিতেই মিথ্যা — প্রতি process-এ, প্রতি pod-এ, প্রতি region-এ একটা

> **আধুনিক চর্চা:** আপনি প্রায় কখনোই Singleton *pattern* লিখবেন না। আপনি আপনার DI container-এ একটা class **singleton lifetime** দিয়ে register করবেন:
> ```csharp
> services.AddSingleton<IConfigStore, ConfigStore>();
> ```
> একই একটামাত্র instance, কিন্তু এটা **inject করা**, তাই এটা দৃশ্যমান, বদলানো যায় আর testable। এটাই ব্যবহার করুন। সবসময়।

### Prototype / Object Pool (পরিচিতি ⚪)

- **Prototype** — বিদ্যমান একটা object ক্লোন করে নতুন বানানো (যখন নির্মাণ ব্যয়বহুল, যেমন একটা আগে থেকে configure করা ML pipeline object)
- **Object Pool** — ব্যয়বহুল object নতুন বানানোর বদলে পুনর্ব্যবহার (DB connection pool, HTTP client pool, thread pool)। আপনি খুব কমই একটা লেখেন; কিন্তু প্রতিদিন একটা ব্যবহার করেন।

---

## ১.৯ Structural pattern — *object কীভাবে জোড়া লাগে*

### Adapter (আর্কিটেক্টের প্রিয়)

**সমস্যা:** আপনি একটা বিদ্যমান class ব্যবহার করতে চান, কিন্তু তার interface আপনার দরকারের সাথে মেলে না।

**বাস্তব জীবন:** একটা ভ্রমণ প্লাগ adapter। দেয়াল বদলায় না; আপনার ল্যাপটপ বদলায় না; adapter মাঝখানে বসে।

```python
# আপনার application-এর নিজের interface — আপনার কোড এটার উপর নির্ভর করে
class FaceDetector(Protocol):
    def detect(self, image: bytes) -> list[Face]: ...

# ভেন্ডরের SDK, যার গঠন আপনার নিয়ন্ত্রণে নেই
class AcmeVisionSDK:
    def analyze_image_v2(self, b64_data: str, opts: dict) -> dict:
        ...

# Adapter
class AcmeFaceDetectorAdapter:
    def __init__(self, sdk: AcmeVisionSDK):
        self._sdk = sdk

    def detect(self, image: bytes) -> list[Face]:
        raw = self._sdk.analyze_image_v2(
            base64.b64encode(image).decode(),
            {"mode": "fast", "return_landmarks": True},
        )
        return [
            Face(
                box=BoundingBox(f["x"], f["y"], f["w"], f["h"]),
                confidence=f["conf"] / 100.0,          # ভেন্ডর ০-১০০ ব্যবহার করে, আমরা ০-১
            )
            for f in raw.get("detected_faces", [])
        ]
```

এখন **একটামাত্র ফাইল** Acme সম্পর্কে জানে। ভেন্ডর বদলানো মানে একটা নতুন adapter। এই ছোট্ট pattern-টাই integration কাজে সবচেয়ে বেশি লাভজনক অভ্যাস — এটা **Anti-Corruption Layer**-এর কোড-স্তরের সংস্করণ (অধ্যায় ০৩)।

### Decorator

**সমস্যা:** একটা object না বদলে, আর subclass-এর বিস্ফোরণ ছাড়াই, তাতে আচরণ যোগ করা।

**বাস্তব জীবন:** কফি। Espresso → +দুধ → +সিরাপ → +হুইপড ক্রিম। প্রতিটা মোড়ক কিছু যোগ করে; মূল পানীয় কখনো বদলায় না।

```csharp
public interface IFaceDetector { Task<IReadOnlyList<Face>> DetectAsync(byte[] image); }

// আসলটা
public class VendorFaceDetector : IFaceDetector { ... }

// মোড়ক ১: caching
public class CachingFaceDetector : IFaceDetector
{
    private readonly IFaceDetector _inner;
    private readonly IDistributedCache _cache;

    public CachingFaceDetector(IFaceDetector inner, IDistributedCache cache)
        => (_inner, _cache) = (inner, cache);

    public async Task<IReadOnlyList<Face>> DetectAsync(byte[] image)
    {
        var key = $"faces:{Convert.ToHexString(SHA256.HashData(image))}";
        if (await _cache.GetAsync<List<Face>>(key) is { } hit) return hit;
        var result = await _inner.DetectAsync(image);
        await _cache.SetAsync(key, result, TimeSpan.FromMinutes(10));
        return result;
    }
}

// মোড়ক ২: retry।  মোড়ক ৩: metrics।  মোড়ক ৪: circuit breaker।
// Registration-এ compose করা:
services.AddScoped<IFaceDetector>(sp =>
    new MetricsFaceDetector(
        new CircuitBreakerFaceDetector(
            new RetryFaceDetector(
                new CachingFaceDetector(
                    new VendorFaceDetector(sp.GetRequiredService<HttpClient>()),
                    sp.GetRequiredService<IDistributedCache>())))));
```

প্রতিটা concern একটা ছোট, স্বাধীনভাবে testable class। এটাই **composition দিয়ে অর্জিত Separation of Concerns**, আর resilience library গুলো (Polly, Resilience4j) ভেতরে এভাবেই কাজ করে।

### Facade

**সমস্যা:** একটা subsystem জটিল। Client-দের একটা সহজ দরজা দিন।

```python
# এই একটা method-এর পেছনে: frame বের করা, quality check, face detection,
# মাথার ভঙ্গি অনুমান, anti-spoofing, challenge validation, scoring, persistence।
class LivenessEngine:
    def verify(self, session_id: str, video: bytes) -> LivenessResult:
        frames  = self._extractor.extract(video)
        quality = self._quality.assess(frames)
        if not quality.acceptable:
            return LivenessResult.rejected(quality.reason)
        faces   = self._detector.detect_all(frames)
        pose    = self._pose.track(faces)
        spoof   = self._anti_spoof.score(frames, faces)
        outcome = self._challenge.validate(session_id, pose)
        return self._scorer.combine(spoof, outcome, quality)
```

Caller এক লাইন লেখে। খেয়াল রাখুন: Facade **সহজ করে**; যাদের অংশগুলো দরকার সেই উন্নত ব্যবহারকারীদের কাছ থেকে subsystem-টা লুকায় না।

### Proxy

**সমস্যা:** একটা object-এ প্রবেশ নিয়ন্ত্রণ করা — একই interface, বাড়তি একটা গেট।

ধরনগুলো:
- **Virtual proxy** — ব্যয়বহুল নির্মাণ পিছিয়ে দেওয়া (একটা ORM relation lazy load করা)
- **Protection proxy** — আগে অনুমতি যাচাই করা
- **Remote proxy** — object অন্য মেশিনে (একটা gRPC/HTTP client আসলে *এটাই*)
- **Caching proxy** — cache থেকে পরিবেশন করা (Decorator-এর সাথে মিলে যায়)

Proxy বনাম Decorator: গঠন প্রায় একই। **উদ্দেশ্য** আলাদা — Decorator আচরণ *যোগ* করে; Proxy প্রবেশ *নিয়ন্ত্রণ* করে।

### Composite

**সমস্যা:** একক object আর object-এর দলকে একইভাবে ব্যবহার করা (গাছের কাঠামো)।

```csharp
public interface IValidationRule { ValidationResult Validate(Application app); }

public class MinimumAgeRule : IValidationRule { ... }       // পাতা
public class DocumentExpiryRule : IValidationRule { ... }   // পাতা

public class AllOfRule : IValidationRule                    // composite
{
    private readonly IReadOnlyList<IValidationRule> _rules;
    public AllOfRule(params IValidationRule[] rules) => _rules = rules;

    public ValidationResult Validate(Application app)
        => _rules.Select(r => r.Validate(app))
                 .Aggregate(ValidationResult.Success, ValidationResult.Combine);
}

// একটা নিয়মের গাছ — আর caller পাতা আর ডালের পার্থক্য বুঝতে পারে না:
IValidationRule policy = new AllOfRule(
    new MinimumAgeRule(18),
    new AnyOfRule(new PassportRule(), new NationalIdRule()),
    new DocumentExpiryRule());
```

**ব্যবহার করুন:** file system, org chart, UI tree, nested permission, rule engine, bill-of-materials-এর জন্য।

### Bridge আর Flyweight (পরিচিতি ⚪)

- **Bridge** — একটা abstraction-কে তার implementation থেকে আলাদা করা যাতে দুটোই বদলাতে পারে (`Shape` × `Renderer`: `SvgCircle`, `CanvasCircle`, `SvgSquare`… এর বিস্ফোরণ এড়াতে)
- **Flyweight** — memory বাঁচাতে অনেক object-এর মধ্যে সাধারণ state ভাগ করা (অক্ষরের glyph, ম্যাপের টাইল, particle system)

---

## ১.১০ Behavioural pattern — *object কীভাবে মিথস্ক্রিয়া করে*

### Strategy 🟢 (যেটা আপনি সবচেয়ে বেশি ব্যবহার করবেন)

**সমস্যা:** একই কাজ করার একাধিক উপায়; রানটাইমে বেছে নিন।

```python
class PricingStrategy(Protocol):
    def price(self, usage: Usage) -> Money: ...

class PerVerificationPricing:
    def price(self, usage): return Money(usage.verifications * Decimal("0.15"), "USD")

class MonthlyFlatPricing:
    def price(self, usage): return Money(Decimal("499"), "USD")

class TieredPricing:
    TIERS = [(1_000, "0.20"), (10_000, "0.12"), (None, "0.08")]
    def price(self, usage): ...

class Subscription:
    def __init__(self, strategy: PricingStrategy):
        self._strategy = strategy
    def invoice(self, usage: Usage) -> Money:
        return self._strategy.price(usage)
```

Strategy হলো **Open/Closed Principle**-এর বাস্তব রূপ। যখনই কোনো *type* বা *mode*-এর উপর ক্রমবর্ধমান `if/elif` দেখবেন, Strategy-র দিকে হাত বাড়ান।

### Observer 🟢

**সমস্যা:** কিছু ঘটলে অজানা সংখ্যক অন্য পক্ষকে জানতে হবে।

```csharp
public interface IDomainEventHandler<in TEvent> { Task HandleAsync(TEvent e, CancellationToken ct); }

public record VerificationCompleted(Guid SessionId, bool Passed, DateTime At);

// তিনটা স্বাধীন শ্রোতা, কেউ কারও সম্পর্কে জানে না
public class SendWebhookHandler   : IDomainEventHandler<VerificationCompleted> { ... }
public class UpdateAnalyticsHandler: IDomainEventHandler<VerificationCompleted> { ... }
public class ReleaseQuotaHandler  : IDomainEventHandler<VerificationCompleted> { ... }
```

Publisher জানে না বা পরোয়া করে না কে শুনছে। **এটাই event-driven architecture-এর process-এর ভেতরের পূর্বপুরুষ** (অধ্যায় ০৬) — একই ধারণা নেটওয়ার্কে বড় করলে আপনি pub/sub পান।

### Command

**সমস্যা:** একটা request-কে object-এ পরিণত করা, যাতে আপনি সেটাকে queue-তে রাখতে, log করতে, undo করতে বা retry করতে পারেন।

```csharp
public record ApproveVerification(Guid SessionId, string ApproverId, string? Note)
    : IRequest<Result>;

public class ApproveVerificationHandler : IRequestHandler<ApproveVerification, Result>
{
    public async Task<Result> Handle(ApproveVerification cmd, CancellationToken ct)
    {
        // ...
    }
}
```

Request এখন **data** হওয়ায় আপনি বিনামূল্যে পান: command-এর একটা audit log, ব্যর্থতায় retry, পরে চালানোর জন্য queue, undo (একটা মিলে যাওয়া compensating command সহ), আর cross-cutting আচরণ ঝোলানোর একটা স্বাভাবিক জায়গা (validation, logging, transaction)। এটাই CQRS আর MediatR-ধাঁচের codebase-এর মেরুদণ্ড।

### State

**সমস্যা:** একটা object তার state অনুযায়ী আলাদা আচরণ করে, আর আপনার সব জায়গায় `if (status == ...)` ছড়িয়ে আছে।

```python
class SessionState(ABC):
    @abstractmethod
    def submit_video(self, session, video): ...
    @abstractmethod
    def cancel(self, session): ...

class PendingState(SessionState):
    def submit_video(self, session, video):
        session.transition_to(ProcessingState())
        return session.enqueue(video)
    def cancel(self, session):
        session.transition_to(CancelledState())

class ProcessingState(SessionState):
    def submit_video(self, session, video):
        raise InvalidOperation("Already processing")
    def cancel(self, session):
        raise InvalidOperation("Cannot cancel while processing")

class CompletedState(SessionState):
    def submit_video(self, session, video):
        raise InvalidOperation("Session already completed")
    def cancel(self, session):
        raise InvalidOperation("Session already completed")
```

এখন অবৈধ transition *গঠনগতভাবেই* অসম্ভব, একটা `if` লিখতে মনে রাখার উপর নির্ভর করে নয়। জীবনচক্র আছে এমন যে কোনো কিছুর জন্য (order, payment, ticket, KYC session, subscription), **কোড লেখার আগে state machine-টা এঁকে ফেলুন।**

### Chain of Responsibility

**সমস্যা:** একটা request কয়েকটা handler-এর মধ্য দিয়ে যাবে, যাদের যে কেউ সেটা সামলাতে বা পরেরজনকে দিতে পারে।

**বাস্তব জীবন:** কাস্টমার সাপোর্টের স্তর — L1 → L2 → engineering। অথবা বিমানবন্দরের নিরাপত্তা: টিকিট চেক → পরিচয় চেক → ব্যাগ স্ক্যান → শরীর স্ক্যান।

```csharp
public abstract class FraudCheck
{
    private FraudCheck? _next;
    public FraudCheck Then(FraudCheck next) { _next = next; return next; }

    public FraudVerdict Evaluate(Application app)
    {
        var verdict = Check(app);
        if (verdict.IsTerminal) return verdict;         // চেইন থামান
        return _next?.Evaluate(app) ?? FraudVerdict.Clean;
    }

    protected abstract FraudVerdict Check(Application app);
}

// আপনি যত HTTP middleware pipeline ব্যবহার করেছেন, সবই এই pattern।
```

### Template Method

**সমস্যা:** কয়েকটা algorithm-এর কঙ্কাল একই, কিন্তু কয়েকটা ধাপে পার্থক্য।

```python
class VerificationPipeline(ABC):
    # কঙ্কালটা নির্দিষ্ট আর একটা জায়গাতেই থাকে
    def run(self, video: bytes) -> Result:
        frames = self.extract_frames(video)
        if not self.check_quality(frames):
            return Result.rejected("poor quality")
        signals = self.analyse(frames)          # subclass গুলো এখানে আলাদা
        score   = self.score(signals)           # ...আর এখানে
        self.persist(score)
        return Result.from_score(score)

    def extract_frames(self, video): ...        # shared default
    def check_quality(self, frames): ...        # shared default
    @abstractmethod
    def analyse(self, frames): ...              # implement করতেই হবে
    @abstractmethod
    def score(self, signals): ...               # implement করতেই হবে

class PassiveLivenessPipeline(VerificationPipeline): ...
class ActiveChallengePipeline(VerificationPipeline): ...
```

এই একটা জায়গাতেই inheritance সত্যিই উজ্জ্বল। (Composition-এর বিকল্প: বদলানো ধাপগুলোর জন্য strategy object পাঠান।)

### আরও কিছু চিনে রাখার মতো ⚪

| Pattern | এক লাইন |
|---------|----------|
| **Iterator** | ভেতরের গঠন প্রকাশ না করেই একটা collection ঘোরা (প্রতিটা আধুনিক ভাষায় অন্তর্নির্মিত) |
| **Mediator** | Object গুলো একে অপরের বদলে একটা hub-এর মাধ্যমে কথা বলে (MediatR; আবার একটা chat room-ও) |
| **Memento** | একটা object-এর state সংরক্ষণ আর পুনরুদ্ধার (undo) |
| **Visitor** | একটা class hierarchy-তে নতুন operation যোগ করা, ওই class গুলো সম্পাদনা না করেই (compiler, AST walking) |
| **Interpreter** | একটা ছোট ভাষার বাক্য মূল্যায়ন করা (rule engine, query DSL) |
| **Null Object** | `null`-এর বদলে কিছুই-না-করা implementation (`NullLogger`, `NoOpCache`) — একগাদা null check মেরে ফেলে |

---

# পর্ব ৩ — Enterprise pattern 🟢

এগুলো এসেছে Martin Fowler-এর *Patterns of Enterprise Application Architecture* আর DDD থেকে। এগুলো কয়েকটা class নয়, পুরো application-এর আকৃতি দেয়।

## ১.১১ Repository

**সমস্যা:** Business logic-এর SQL, ORM বা Mongo সম্পর্কে জানা উচিত নয়।

**মনের মডেল:** একটা Repository ভান করে যে সে domain object-এর একটা **in-memory collection**।

```csharp
// DOMAIN প্রজেক্টে — business ভাষায় প্রকাশিত, কোথাও কোনো SQL নেই
public interface IVerificationSessionRepository
{
    Task<VerificationSession?> GetAsync(SessionId id, CancellationToken ct);
    Task<IReadOnlyList<VerificationSession>> GetExpiredAsync(DateTime before, CancellationToken ct);
    Task AddAsync(VerificationSession session, CancellationToken ct);
    Task UpdateAsync(VerificationSession session, CancellationToken ct);
}

// INFRASTRUCTURE প্রজেক্টে
public class EfVerificationSessionRepository : IVerificationSessionRepository
{
    private readonly AppDbContext _db;
    public EfVerificationSessionRepository(AppDbContext db) => _db = db;

    public Task<VerificationSession?> GetAsync(SessionId id, CancellationToken ct) =>
        _db.Sessions.Include(s => s.Attempts)
                    .FirstOrDefaultAsync(s => s.Id == id, ct);
    // ...
}
```

### ভালো repository-র নিয়ম

১. **প্রতি Aggregate Root-এ একটা repository**, প্রতি table-এ নয় (অধ্যায় ০৩)। `IOrderRepository`, `IOrderLineRepository` নয়।
২. **Domain object ফেরত দিন**, কখনো `DataTable`, `DbSet` বা ভেন্ডরের type নয়।
৩. **`IQueryable` বাইরে ফাঁস করবেন না** — করলে caller যে কোনো query লিখতে পারবে, আর আপনি কিছুই পাননি। Database-এর ব্যাপারগুলো সোজা ফিরে আসবে।
৪. **Method-এর নাম business ভাষায় দিন** — `GetExpiredAsync`, `GetPendingReviewAsync`, `FindByStatusAndDate` নয়।
৫. **২০টা method সহ একটা generic `IRepository<T>` বানাবেন না** — এটা ISP লঙ্ঘন, আর এটা প্রতিটা aggregate-কে এমন operation সাপোর্ট করতে বাধ্য করে যেগুলোর তার জন্য কোনো মানে নেই।

### সৎ পাল্টা যুক্তি

কেউ কেউ বলেন EF Core বা SQLAlchemy-র মতো ORM-এর উপর একটা repository অর্থহীন বাড়তি স্তর — ORM-এর `DbSet`/`Session` *ইতিমধ্যেই* একটা repository আর একটা Unit of Work।

কথাটা ন্যায্য। Repository ব্যবহার করুন যখন:
- আপনার domain model DB ছাড়াই বিশুদ্ধ আর testable থাকতে হবে (সাধারণত এটাই নির্ধারক)
- আপনার জটিল query আছে যেগুলোকে নাম দিয়ে পুনর্ব্যবহার করতে চান
- Data store বদলানোর সত্যিকারের সম্ভাবনা আছে, অথবা আপনার দুটো আছে (SQL + একটা search index)

বাদ দিন যখন: আপনার একটা ছোট CRUD service আর ORM-ই ইতিমধ্যে abstraction। **প্রতিবর্তী ক্রিয়ায় স্তর যোগ করবেন না।**

## ১.১২ Unit of Work

**সমস্যা:** একটা business operation কয়েকটা object ছোঁয়। হয় সব পরিবর্তন টিকবে, নয় কোনোটাই না।

**বাস্তব জীবন:** একটা ব্যাংক ট্রান্সফার। এক account থেকে কাটুন, আরেকটায় জমা দিন। দুটোই, নয়তো কোনোটাই না। কখনোই একটা নয়।

```csharp
public interface IUnitOfWork
{
    Task<int> SaveChangesAsync(CancellationToken ct = default);
}

public class TransferMoneyHandler
{
    private readonly IAccountRepository _accounts;
    private readonly IUnitOfWork _uow;

    public async Task Handle(TransferMoney cmd, CancellationToken ct)
    {
        var from = await _accounts.GetAsync(cmd.From, ct) ?? throw new NotFound(cmd.From);
        var to   = await _accounts.GetAsync(cmd.To, ct)   ?? throw new NotFound(cmd.To);

        from.Withdraw(cmd.Amount);   // domain rule: যথেষ্ট টাকা আছে? account কি জব্দ?
        to.Deposit(cmd.Amount);

        await _uow.SaveChangesAsync(ct);   // একটাই transaction, দুটো row, নয়তো কিছুই না
    }
}
```

EF Core-এর `DbContext` আর SQLAlchemy-র `Session` ইতিমধ্যেই **Unit of Work**। এগুলো পরিবর্তন track করে আর একটা transaction-এ flush করে। এগুলোকে একটা `IUnitOfWork` interface-এ মোড়ানোর মূল কারণ application layer-কে EF-এর type থেকে মুক্ত রাখা।

**আর্কিটেক্টের নোট:** Unit of Work **একটা database**-এর ভেতরে চমৎকার কাজ করে। Service/database-এর মধ্যে এর কোনো অস্তিত্ব নেই — সেখানেই **Saga** আসে (অধ্যায় ০৫)। এই সীমানাটা ঠিক কোথায় তা জানা একজন আর্কিটেক্টের মূল দক্ষতা।

## ১.১৩ Specification

**সমস্যা:** "কোন object গুলো যোগ্য?" — এই business rule গুলো validation কোড, query কোড আর UI কোডের মধ্যে পুনরাবৃত্ত হয়।

```csharp
public abstract class Specification<T>
{
    public abstract Expression<Func<T, bool>> ToExpression();
    public bool IsSatisfiedBy(T candidate) => ToExpression().Compile()(candidate);

    public Specification<T> And(Specification<T> other) => new AndSpecification<T>(this, other);
    public Specification<T> Or(Specification<T> other)  => new OrSpecification<T>(this, other);
    public Specification<T> Not()                       => new NotSpecification<T>(this);
}

public class ExpiredSessionSpec : Specification<VerificationSession>
{
    private readonly DateTime _now;
    public ExpiredSessionSpec(DateTime now) => _now = now;
    public override Expression<Func<VerificationSession, bool>> ToExpression()
        => s => s.CreatedAt.AddMinutes(15) < _now && s.Status == SessionStatus.Pending;
}

public class HighRiskSpec : Specification<VerificationSession>
{
    public override Expression<Func<VerificationSession, bool>> ToExpression()
        => s => s.RiskScore > 0.7 || s.AttemptCount >= 3;
}

// নিয়মটা একবার সংজ্ঞায়িত, আর দুই জায়গাতেই ব্যবহৃত:
var spec = new ExpiredSessionSpec(DateTime.UtcNow).And(new HighRiskSpec());

bool needsReview = spec.IsSatisfiedBy(session);                 // in-memory যাচাই
var toReview     = await _db.Sessions.Where(spec.ToExpression()) // SQL-এ অনূদিত
                                     .ToListAsync(ct);
```

**ব্যবহার করুন যখন:** একই "কোনগুলো যোগ্য" নিয়ম একাধিক জায়গায় দেখা যায়, অথবা ব্যবহারকারীরা শর্ত জুড়ে filter বানাতে পারেন। **বাদ দিন যখন:** আপনার তিনটা সহজ query আছে — একটা নাম দেওয়া repository method সহজ আর পরিষ্কার।

## ১.১৪ Service Layer

**সমস্যা:** Orchestration কোথায় থাকে — যে কোড domain rule-ও নয়, controller-ও নয়?

তিন ধরনের service নিয়ে যে বিভ্রান্তি, তার সমাধান:

| ধরন | থাকে | যা থাকে | উদাহরণ |
|------|----------|----------|---------|
| **Application Service** | Application layer | Orchestration, transaction, authorisation যাচাই, repo আর বাইরের service-এ call। **কোনো business rule নয়।** | `VerificationService.VerifyAsync()` |
| **Domain Service** | Domain layer | Business logic যা একটা entity-র নয়। **কোনো I/O নয়।** | `RiskScoringService.Score(session, history)` |
| **Infrastructure Service** | Infrastructure layer | কারিগরি কাজ | `S3VideoStorage`, `SendGridEmailSender` |

```python
# APPLICATION SERVICE — একজন পাতলা কন্ডাক্টর। রেসিপির মতো পড়া যায়।
class VerificationAppService:
    def __init__(self, sessions, detector, storage, events, uow):
        self._sessions, self._detector = sessions, detector
        self._storage, self._events, self._uow = storage, events, uow

    async def verify(self, cmd: VerifyCommand) -> VerificationDto:
        session = await self._sessions.get(cmd.session_id)
        if session is None:
            raise SessionNotFound(cmd.session_id)

        video_ref = await self._storage.save(cmd.video)          # infrastructure
        signals   = await self._detector.analyse(cmd.video)      # infrastructure
        session.record_attempt(signals, video_ref)               # DOMAIN সিদ্ধান্ত নেয়

        await self._sessions.update(session)
        await self._uow.commit()
        await self._events.publish(session.pull_domain_events())
        return VerificationDto.from_domain(session)
```

> **সুস্থ application service-এর পরীক্ষা:** এটা ধাপের তালিকার মতো পড়া যাবে, আর **business rule নিয়ে কোনো `if` থাকবে না**। টাকা, যোগ্যতা, সীমা বা status নিয়ে প্রতিটা `if` domain-এর।

**যে anti-pattern এড়াবেন:** *Anemic Domain Model* — এমন entity যেগুলো শুধু getter/setter সহ property-র বস্তা, আর সব logic service-এ বসে আছে। তখন আপনার কাছে OOP-র পোশাক পরা procedural কোড থাকে; নিয়মগুলো service-এর মধ্যে পুনরাবৃত্ত হয়, আর কেউ খুঁজে পায় না।

## ১.১৫ DTO — Data Transfer Object

**সমস্যা:** আপনার ভেতরের model আপনার বাইরের contract হওয়া উচিত নয়।

```csharp
// DOMAIN — সমৃদ্ধ, সুরক্ষিত, অভ্যন্তরীণ
public class VerificationSession
{
    public SessionId Id { get; private set; }
    public CustomerId CustomerId { get; private set; }
    internal string VendorApiKey { get; private set; }       // কখনোই বাইরে যাবে না
    public decimal InternalRiskScore { get; private set; }   // কখনোই বাইরে যাবে না
    private readonly List<Attempt> _attempts = new();
    public IReadOnlyList<Attempt> Attempts => _attempts;

    public void RecordAttempt(Signals s) { /* নিয়ম */ }
}

// API CONTRACT — সমতল, স্পষ্ট, স্থিতিশীল, নিরাপদ
public record VerificationResponse(
    string SessionId,
    string Status,
    bool Passed,
    int AttemptsUsed,
    int AttemptsRemaining,
    DateTime CompletedAt);
```

### DTO কেন গুরুত্বপূর্ণ (চারটা কারণ)

১. **Security** — আপনি ভুল করেও `VendorApiKey` বা `InternalRiskScore` ফাঁস করতে পারবেন না। Entity স্বয়ংক্রিয়ভাবে serialise করা একটা সত্যিকারের, সাধারণ breach-এর পথ।
২. **Stability** — একটা domain field-এর নাম বদলান, public API ভাঙবে না (আপনার mapper সেটা শুষে নেয়)
৩. **আকৃতি** — API সমতল করতে, জোড়া লাগাতে বা হিসাব করতে পারে (`AttemptsRemaining`), domain নোংরা না করেই
৪. **Over-posting থেকে সুরক্ষা** — শুধু অনুমোদিত field সহ একটা request DTO client-কে JSON body-তে `IsAdmin: true` বসাতে বাধা দেয়

> **কঠোর নিয়ম: কখনো API-র উপর domain entity সরাসরি প্রকাশ করবেন না।** আর কখনো সরাসরি input হিসেবেও নেবেন না। সীমানায় map করুন — হাতে, অথবা Mapster/AutoMapper/Pydantic দিয়ে।

## ১.১৬ Dependency Injection

**DIP** হলো নীতি (১.২)। **DI** হলো কৌশল। **IoC container** হলো টুল।

### Inject করার তিন উপায়

```csharp
// ১. CONSTRUCTOR INJECTION — প্রায় ৯৫% ক্ষেত্রে এটাই ব্যবহার করুন
public class OrderService
{
    private readonly IOrderRepository _repo;
    public OrderService(IOrderRepository repo) => _repo = repo;   // আবশ্যক, immutable
}

// ২. PROPERTY INJECTION — সত্যিকারের optional dependency-র জন্য
public class OrderService
{
    public ILogger Logger { get; set; } = NullLogger.Instance;    // নিরাপদ default আছে
}

// ৩. METHOD INJECTION — dependency প্রতি call-এ বদলায়
public decimal Calculate(Order o, ITaxPolicy policy) => policy.Apply(o);
```

### Lifetime — এটা ভুল করলে রাত ৩টার bug পাবেন

| Lifetime | প্রতি কিসে একটা instance | যার জন্য | ক্লাসিক bug |
|----------|-----------------|---------|-------------|
| **Transient** | প্রতিবার চাওয়ায় | হালকা, stateless জিনিস | লুপের ভেতর ব্যয়বহুল object বানানো |
| **Scoped** | প্রতি HTTP request / প্রতি unit of work | `DbContext`, per-request context | — |
| **Singleton** | পুরো application | Config, cache, HTTP client, pool | **Captive dependency**: একটা Singleton একটা Scoped `DbContext` ধরে রেখেছে। সেই DbContext এখন চিরকাল বাঁচে, request-এর মধ্যে shared হয়, আর thread-safe নয়। বিশৃঙ্খলা। |

> বেশিরভাগ DI container captive dependency ধরতে পারে। **ওই validation চালু করুন** (.NET-এ `ValidateScopes = true`, `ValidateOnBuild = true`)। এটা একটা রহস্যময় production bug-কে একটা startup error-এ পরিণত করে।

### DI কেন architecture-এর বিষয়, কোডিংয়ের কৌশল নয়

- রানটাইমে DIP এভাবেই বাস্তবে প্রয়োগ হয়
- এটা dependency **দৃশ্যমান** করে — একটা constructor পড়লেই আপনি জানেন class-টার ঠিক কী লাগে। ৯টা জিনিস লাগলে SRP ভাঙা, আর এখন আপনি সেটা *দেখতে* পাচ্ছেন।
- এটা testing তুচ্ছ করে দেয় (fake পাঠান)
- এটা composition root-এ Decorator pattern সম্ভব করে
- এটা আপনাকে **একটা জায়গা** দেয় (composition root) যেখানে সব wiring ঘোষিত

## ১.১৭ CQRS — Command Query Responsibility Segregation

**মূল ধারণা:** Data **বদলাতে** যে model ব্যবহার করেন, সেটাই data **পড়তে** ব্যবহার করতে হবে এমন নয়।

**কেন:** Write-এ লাগে validation, invariant, transaction আর একটা সমৃদ্ধ object graph। Read-এ লাগে গতি, সমতল আকৃতি আর join। একটা model দিয়ে দুটোই পরিবেশন করলে দুটোই আপস করে।

### স্তর ১ — শুধু কোডের পথ আলাদা করুন (এখান থেকে শুরু করুন)

```csharp
// WRITE দিক: সমৃদ্ধ domain, পুরো aggregate, সব নিয়ম বলবৎ
public record ApproveVerification(Guid SessionId, string ApproverId) : IRequest;

public class ApproveVerificationHandler : IRequestHandler<ApproveVerification>
{
    public async Task Handle(ApproveVerification cmd, CancellationToken ct)
    {
        var session = await _repo.GetAsync(cmd.SessionId, ct);  // aggregate load করে
        session.Approve(cmd.ApproverId);                        // invariant বলবৎ করে
        await _uow.SaveChangesAsync(ct);
    }
}

// READ দিক: কোনো domain model নেই — সোজা একটা দ্রুত projection-এ যান
public class GetSessionListHandler : IRequestHandler<GetSessionList, IReadOnlyList<SessionRow>>
{
    private readonly IDbConnection _db;       // সাধারণ Dapper / raw SQL
    public async Task<IReadOnlyList<SessionRow>> Handle(GetSessionList q, CancellationToken ct)
        => (await _db.QueryAsync<SessionRow>(
                """
                SELECT s.id, s.status, c.name AS customer_name, s.created_at, s.score
                FROM   sessions s
                JOIN   customers c ON c.id = s.customer_id
                WHERE  s.tenant_id = @TenantId AND s.created_at >= @From
                ORDER  BY s.created_at DESC
                LIMIT  @Take OFFSET @Skip
                """, q)).ToList();
}
```

শুধু এটুকুই বিশাল যন্ত্রণা দূর করে: একটা grid view বানানোর জন্য ORM-কে আর অত্যাচার করতে হয় না, আর ৫টা কলাম দেখাতে ১২ table-এর aggregate load করতে হয় না।

### স্তর ২ — আলাদা data store (শুধু যখন দরকার)

```
                      ┌──────────────┐
  Command ──────────► │ Write DB     │  (Postgres, normalised, transactional)
                      └──────┬───────┘
                             │ event / CDC
                             ▼
                      ┌──────────────┐
  Query    ◄───────── │ Read store   │  (Elasticsearch / Mongo / materialised view)
                      └──────────────┘
```

**আপনি পান:** read আর write স্বাধীনভাবে scale করে; প্রতিটা store তার কাজের জন্য optimised; জটিল search সহজ হয়ে যায়।
**আপনি দাম দেন:** eventual consistency (একজন ব্যবহারকারী নিজের লেখা সাথে সাথে দেখতে নাও পারেন), বানানো আর চালানোর জন্য একটা synchronisation pipeline, আর দ্বিগুণ storage।

> **CQRS কখন ব্যবহার করবেন:** read আর write-এর চাপ খুবই আলাদা (যেমন ১০০০:১), অথবা reporting query আপনার OLTP database মেরে ফেলছে, অথবা আপনার জটিল search দরকার।
> **কখন নয়:** সাধারণ CRUD। একটা মৌলিক admin screen-এ CQRS নিছক আনুষ্ঠানিকতা। স্তর ১ থেকে শুরু করুন, আর সত্যিকারের সমস্যা মাপার পরেই স্তর ২-তে যান।

### "নিজের লেখা নিজে পড়া"-র ফাঁদ

আলাদা store থাকলে ব্যবহারকারী Save চাপেন আর তারপর পুরনো মানটাই দেখেন। CQRS নিয়ে এটাই এক নম্বর অভিযোগ। প্রচলিত সমাধান:

- নতুন মানটা সরাসরি command-এর response থেকে ফেরত দিন (আবার query করবেন না)
- Client-এ UI আশাবাদীভাবে update করুন
- ওই ব্যবহারকারীর read কয়েক সেকেন্ডের জন্য write store-এ পাঠান ("sticky" read)
- একটা স্পষ্ট "প্রক্রিয়াধীন…" অবস্থা দেখান, যাতে UI কখনো মিথ্যা না বলে

## ১.১৮ Domain Event

**সমস্যা:** Domain-এ গুরুত্বপূর্ণ কিছু ঘটেছে, আর সিস্টেমের কয়েকটা অংশকে সাড়া দিতে হবে — কিন্তু domain-এর তাদের সম্পর্কে জানা উচিত নয়।

```csharp
public abstract record DomainEvent(DateTime OccurredAt);
public record VerificationPassed(SessionId SessionId, CustomerId CustomerId, decimal Score, DateTime OccurredAt)
    : DomainEvent(OccurredAt);

public class VerificationSession
{
    private readonly List<DomainEvent> _events = new();
    public IReadOnlyList<DomainEvent> DomainEvents => _events;
    public void ClearEvents() => _events.Clear();

    public void RecordAttempt(Signals signals)
    {
        if (_attempts.Count >= MaxAttempts) throw new TooManyAttemptsException(Id);

        var passed = signals.LivenessScore > PassThreshold && !signals.SpoofDetected;
        _attempts.Add(new Attempt(signals, passed));

        if (passed)
        {
            Status = SessionStatus.Passed;
            _events.Add(new VerificationPassed(Id, CustomerId, signals.LivenessScore, DateTime.UtcNow));
        }
        else if (_attempts.Count >= MaxAttempts)
        {
            Status = SessionStatus.Failed;
            _events.Add(new VerificationFailed(Id, CustomerId, "max attempts", DateTime.UtcNow));
        }
    }
}
```

Session একটা **সত্য** ঘোষণা করে। সে ইমেইল পাঠায় না, webhook call করে না, analytics update করে না। ওগুলো স্বাধীন শ্রোতারা সামলায়:

```csharp
public class SendWebhookOnPass       : INotificationHandler<VerificationPassed> { ... }
public class ReleaseQuotaOnPass      : INotificationHandler<VerificationPassed> { ... }
public class UpdateDashboardOnPass   : INotificationHandler<VerificationPassed> { ... }
```

### Event কখন পাঠানো হয়? (গুরুত্বপূর্ণ খুঁটিনাটি)

`SaveChanges`-এর **আগে** — handler গুলো একই transaction-এর ভেতরে চলে। সামঞ্জস্যপূর্ণ, কিন্তু একটা ধীর/ব্যর্থ handler পুরো business operation ফিরিয়ে দেয়। Domain-এর ভেতরের পার্শ্বপ্রতিক্রিয়ার জন্য ঠিক আছে।

`SaveChanges`-এর **পরে** — business পরিবর্তনটা নিরাপদ; handler গুলো পরে চলে। কিন্তু commit আর dispatch-এর মাঝখানে process crash করলে **event হারিয়ে যায়**। এটাই ক্লাসিক **dual-write সমস্যা**।

**সঠিক সমাধান হলো Outbox pattern:** business data-র *একই transaction-এ* event-টা একটা `outbox` table-এ লিখুন; একটা আলাদা process outbox পড়ে আর publish করে। Atomic, আর কোনো event হারায় না। পূর্ণ আলোচনা অধ্যায় ০৬-এ — এটা পুরো বইয়ের সবচেয়ে মূল্যবান pattern গুলোর একটা।

### Event-এর নামকরণ

- **অতীত কাল, সবসময়।** `OrderPlaced`, `PlaceOrder` নয় (সেটা একটা command)।
- **Business ভাষা।** `CustomerVerified`, `SessionRowUpdated` নয়।
- **Immutable।** একটা event অতীতের একটা সত্য; সত্য বদলায় না।
- **Handler-দের যা লাগে** তা রাখুন, সাথে ID আর একটা timestamp — তবে মনে রাখুন মোটা event coupling তৈরি করে (অধ্যায় ০৬-এ event-carried state transfer বনাম notification আছে)।

---

## ১.১৯ সাধারণ ভুল

১. **Pattern-জ্বর** — pattern প্রয়োগ করা কারণ আপনি শিখেছেন, সমস্যা আছে বলে নয়। একটা config ফাইলের জন্য `FactoryProviderStrategyBuilder`।
২. **Anemic domain model** — শুধু getter/setter সহ entity; সব logic service-এ। খুবই সাধারণ, আর এটা নীরবে DDD মেরে ফেলে।
৩. **২৫টা method সহ generic `IRepository<T>`** — ISP লঙ্ঘন; প্রতিটা aggregate-এ অর্থহীন operation চাপায়।
৪. **Repository থেকে `IQueryable` ফাঁস** — সব abstraction শেষ, আর DB-র গঠন আবার আপনার business কোডে।
৫. **Singleton-এর অপব্যবহার** — global mutable state, test করা যায় না, লুকানো dependency।
৬. **কাকতালীয় মিলকে DRY করা** — আজ দেখতে একরকম দুটো নিয়ম ঝালাই করে দেওয়া হয়, আর ভুল abstraction-এর দাম duplication-এর চেয়ে বেশি।
৭. **API-তে entity প্রকাশ করা** — দুর্ঘটনাজনিত data প্রকাশের প্রধান কারণ।
৮. **১২টা dependency সহ constructor** — DI এটা তৈরি করেনি; এটা একটা SRP লঙ্ঘন *প্রকাশ* করেছে। Class ঠিক করুন, constructor লুকাবেন না।
৯. **সবকিছুর জন্য interface** — একটা implementation, একটা interface, চিরকাল। যদি কখনোই একটাই implementation থাকে আর testing-এর জন্য seam না লাগে, তাহলে interface-টা শুধুই গোলমাল।
১০. **গভীর inheritance hierarchy** — ৫ স্তর, আর `Save()` কী করে কেউ অনুমান করতে পারে না।

---

## ১.২০ আর্কিটেক্টের চেকলিস্ট

- [ ] আমি কি **কোনো** database, network বা file system ছাড়াই business rule গুলো unit-test করতে পারি?
- [ ] Domain layer কি কোনো framework, driver বা SDK import করে? (করা উচিত নয়।)
- [ ] প্রতিটা business rule-এর জন্য কি ঠিক **একটাই** জায়গা আছে?
- [ ] বাইরের সিস্টেমগুলো কি **আমার** interface-এর পেছনে (Adapter), সরাসরি ব্যবহৃত নয়?
- [ ] Entity কি API-তে প্রকাশিত? (না হওয়া উচিত।)
- [ ] একজন নতুন ডেভেলপার কি ২ মিনিটের মধ্যে খুঁজে পাবেন কোনো নির্দিষ্ট নিয়ম কোথায় আছে?
- [ ] Dependency গুলো কি constructor-এ দৃশ্যমান, static/singleton-এ লুকানো নয়?
- [ ] `Utils`, `Helper`, `Manager` বা `Common` নামের কোনো class আছে? (Cohesion-এর সতর্কতা।)
- [ ] Value object কি immutable?
- [ ] Type বা mode-এর উপর ক্রমবর্ধমান `if/switch` চেইন আছে? (Strategy-র প্রার্থী।)
- [ ] জীবনচক্র আছে এমন কিছুর কি আঁকা state machine আছে?
- [ ] DI lifetime গুলো কি startup-এ validate করা হয়?

---

## ১.২১ নিজেকে যাচাই

১. Coupling আর cohesion-এর সংজ্ঞা দিন। প্রতিটার লক্ষ্য কী?
২. "এক class, এক কাজ" কেন SRP-র *ভুল* বক্তব্য? সঠিকভাবে বলুন।
৩. কোডে একটা Liskov লঙ্ঘন দেখান, আর ব্যাখ্যা করুন compiler কেন এটা ধরতে পারে না।
৪. `IOrderRepository` interface-টা শারীরিকভাবে কোথায় থাকা উচিত, আর এটা কেন গুরুত্বপূর্ণ?
৫. কখন duplication abstraction-এর চেয়ে ভালো? একটা বাস্তব উদাহরণ দিন।
৬. YAGNI কোথায় প্রযোজ্য *নয়*? চারটা জিনিসের নাম বলুন।
৭. Adapter বনাম Decorator বনাম Proxy: একই গঠন, আলাদা উদ্দেশ্য। প্রতিটার উদ্দেশ্য বলুন।
৮. Singleton কেন সাধারণত ভুল উত্তর, আর সঠিকটা কী?
৯. Application Service আর Domain Service-এর পার্থক্য কী?
১০. Anemic domain model কী, আর এটা কেন সমস্যা?
১১. CQRS স্তর ১ বনাম স্তর ২ ব্যাখ্যা করুন। স্তর ২ কখন যুক্তিসঙ্গত?
১২. Domain event-এর dual-write সমস্যা কী, আর কোন pattern এটা ঠিক করে?

---

## ১.২২ মূল কথাগুলো

- সবকিছুই নেমে আসে **low coupling, high cohesion**-এ
- **SOLID** হলো সেটা অর্জনের পাঁচটা কৌশল — architecture-এর দিক থেকে DIP-ই নির্ণায়ক
- **DRY প্রযোজ্য জ্ঞানের ক্ষেত্রে, টেক্সটের ক্ষেত্রে নয়।** ভুল abstraction-এর দাম duplication-এর চেয়ে বেশি
- **Feature-এর জন্য YAGNI; কিন্তু যা পরে বসানো ব্যয়বহুল তার জন্য আগেই ভাবুন**
- **আচরণ compose করুন; পরিচয় inherit করুন**
- **Immutability** thread safety, cache করার ক্ষমতা আর মানসিক শান্তি কিনে দেয় — value object, DTO আর event-এ ব্যবহার করুন
- Pattern একটা **পরিভাষা**, কেনাকাটার তালিকা নয় — আবিষ্কৃত, প্রযুক্ত নয়
- প্রতিটা বাইরের সীমানায় **Adapter** — integration কাজে সবচেয়ে লাভজনক অভ্যাস
- **কখনো API-র উপর domain entity প্রকাশ করবেন না**
- Domain **বিশুদ্ধ** রাখুন: কোনো I/O নয়, কোনো framework নয়, পুরোপুরি unit-testable

---

**পরবর্তী:** [অধ্যায় ০২ — Architecture Style](02-architecture-styles.md)

**ইংরেজি সংস্করণ:** [Chapter 01](../01-software-engineering-foundations.md) · **[সূচিপত্র](README.md)**
