# .NET Fundamentals

## What is .NET?

**.NET** is a free, open-source, cross-platform development platform created by Microsoft. It is used to build various types of applications such as:

- Web applications
- Mobile apps
- Desktop applications
- Cloud services
- IoT apps

## Key Components of .NET

### 1. CLI (Common Language Infrastructure)
A standardized specification by Microsoft that defines:

- The runtime environment to execute code.
- How different programming languages (C#, VB.NET, F#) can work together.
- A common type system and metadata format.

CLI ensures language interoperability and platform independence.

### 2. CLR (Common Language Runtime)
The **CLR** is the core runtime engine of the .NET platform responsible for managing the execution of .NET applications. When you compile your .NET code (C#, F#, etc.), it's converted into Intermediate Language (IL). This IL is executed by the CLR, which compiles it into native machine code using the JIT compiler.

#### Responsibilities of CLR:

| Component             | Description                                                          |
|-----------------------|----------------------------------------------------------------------|
| **Class Loader**      | Loads classes and assemblies into memory for execution.             |
| **Memory Manager**    | Allocates and manages memory (heap and stack).                      |
| **Garbage Collector** | Automatically frees unused memory to prevent leaks.                 |
| **JIT Compiler**      | Converts Intermediate Language (IL) code into native machine code.  |
| **Exception Manager** | Handles structured error handling (try-catch-finally).              |
| **Thread Manager**    | Manages application threads and concurrency.                        |
| **Security Manager**  | Enforces code access and role-based security policies.              |
| **Code Verifier**     | Ensures IL code is type-safe before execution.                       |
| **Interop Services**  | Enables .NET code to interact with unmanaged code or COM components.|


### 3. IL (Intermediate Language)
- IL is CPU-independent, intermediate code generated from your high-level source code (C#, VB.NET).
- It acts as a portable assembly language for the CLR.
- At runtime, the JIT compiler translates IL to machine code specific to the CPU.

### 4. CLS (Common Language Specification)
A set of rules and standards that all .NET languages must follow to ensure interoperability and compatibility. It guarantees that code written in one language can use code written in another.

### 5. BCL (Base Class Library) & FCL (Framework Class Library)
- **BCL**: The foundational library with core classes like `System.String`, collections, file I/O, and threading.
- **FCL**: A broader set of libraries including BCL plus web, data, and UI frameworks like ASP.NET, ADO.NET, Windows Forms.

### 6. CSC (C# Compiler)
Compiles C# source code into Intermediate Language (IL) code and generates .dll or .exe assemblies.

### 7. ADO.NET
A .NET data access technology for working with relational databases.

- **Connected Mode**: Uses `SqlDataReader` for fast forward-only data access.
- **Disconnected Mode**: Uses `DataSet` and `SqlDataAdapter` to manipulate data offline.

Common components:
- `SqlConnection`, `SqlCommand`, `SqlDataReader`, `SqlDataAdapter`, `DataSet`, `SqlTransaction`.

## 9. .NET Framework Architecture

## .NET Framework Architecture

### Layers Overview:

1. **Application Layer**  
   Your user applications: Console, Windows Forms, WPF, ASP.NET, etc.

2. **Framework Class Library (FCL/BCL)**  
   Predefined reusable classes and APIs for all kinds of common programming tasks.

3. **Common Language Runtime (CLR)**  
   The execution engine providing services like memory management, security, and exception handling.

4. **Operating System**  
   Underlying platform (primarily Windows for .NET Framework).

### Execution Lifecycle

1. **Source Code**  
   Write code in C#, VB.NET, or F#.

2. **Compilation**  
   The compiler (`csc.exe`) compiles source code into **IL code + metadata**, packaged as assemblies (.exe or .dll).

3. **Loading**  
   The CLR loads the assemblies and required classes via the Class Loader.

4. **Verification & Security**  
   Code is verified for type safety and checked by the Security Manager.

5. **JIT Compilation**  
   IL code is compiled into native machine code on demand by the Just-In-Time compiler.

6. **Execution**  
   Native machine code is executed by the CPU. CLR manages runtime services like exception handling, threading, and garbage collection.

7. **Garbage Collection**  
   The Garbage Collector automatically cleans up unused objects to free memory.

+------------------------+
| Source Code (C#)       |
+------------------------+
        |
        v
+------------------------+
| C# Compiler (CSC.exe)  |
| IL + Metadata → EXE    |
+------------------------+
        |
        v
+------------------------+
| CLR Execution Starts   |
+------------------------+
| Class Loader           |  → Loads Main(), Worker
| Security Manager       |  → Verifies code trust
| Memory Manager         |  → Allocates heap & stack
| JIT Compiler           |  → IL → Machine Code
| Exception Manager      |  → Handles try-catch
| Thread Manager         |  → Manages Thread.Sleep
| Garbage Collector      |  → Cleans up after finish
+------------------------+
        |
        v
+------------------------+
| Native Code Executes   |
+------------------------+

## Key Differences: .NET Framework vs .NET Core vs ASP.NET Core

| Aspect                | .NET Framework                             | .NET Core                               | ASP.NET Core                         |
|-----------------------|-------------------------------------------|----------------------------------------|------------------------------------|
| Platform              | Windows only                              | Cross-platform                         | Cross-platform (on .NET Core)      |
| Open Source           | Mostly proprietary                        | Fully open source                      | Fully open source                  |
| Deployment            | Requires full framework installed        | Side-by-side, self-contained deployment | Runs on .NET Core runtime          |
| Modularity            | Monolithic                               | Modular, NuGet package-based           | Modular middleware pipeline        |
| Performance           | Good, but heavier                        | High-performance, lightweight          | High-performance, lightweight      |
| Primary Usage         | Legacy desktop and web apps              | Modern apps, cloud, microservices      | Modern web applications and APIs   |
| UI Support            | Windows Forms, WPF                       | Limited (supports Windows Forms, WPF on Windows) | Web UI only                       |
| Cloud & Containers    | Limited                                 | Designed for cloud, containers          | Built for cloud-native web apps    |