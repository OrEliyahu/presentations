# Testing at the Product Boundary

## How I test software in the AI era

AI made writing code cheap. It did not make confidence cheap.

An agent can produce several implementations before a person has reviewed one. The bottleneck is no longer typing the code. The bottleneck is knowing whether the code fulfills the product requirement without breaking an old promise.

My default is therefore simple:

> Test what the product promises, through the highest realistic entry point, until the last visible effect.

For a backend, that usually means a real HTTP request or command-line input. The test should cross the real authentication, validation, request routing, business logic, database, and internal event paths. It should stop only where the application leaves our control, such as an email provider, queue, analytics service, or object store.

At that external seam, use a controlled implementation that captures what would have been sent. Keep everything inside the application real.

## A test is executable product intent

A useful test is a repeatable product statement:

> When a staff member reactivates a withdrawn student, the student becomes active, the change is recorded, and no withdrawal notice is sent.

That statement should remain true whether the implementation uses one service or five, synchronous calls or events, arrays or maps.

A test such as this says much less:

```ts
expect(notificationService.send).not.toHaveBeenCalled();
```

It describes one implementation. It does not prove what a user or another system observes.

A behavior-level assertion describes the promise:

```ts
expect(capturedWithdrawalNotices).toEqual([]);
```

The first test is coupled to the route taken through the code. The second is coupled to the product outcome.

## The test pyramid

The classic test pyramid has three broad levels:

1. **Unit tests** enter through a function or class and isolate it from collaborators.
2. **Integration tests** enter where a real backend caller enters, usually through HTTP or a command-line interface.
3. **End-to-end tests** are integration tests whose entry point is the client application, such as a browser or mobile app.

These labels are not exact. The important question is not what we call a test. The important question is:

> Which real boundary did this test cross?

The pyramid was a rational response to cost. Broad tests were slow to write, slow to run, and easy to break. Teams used many cheap unit tests and a small number of expensive integration tests to get feedback quickly enough.

That shape is not a law of software. It is a response to the cost of broad tests. If we make high-level tests fast, reliable, and readable, the best balance changes.

## Why unit tests are my last resort

A mock-heavy unit test often gives the code its answers and then checks that the code repeats them.

```ts
const accountStore = {
  find: jest.fn().mockResolvedValue(fakeAccount),
};
const notifier = {
  sync: jest.fn().mockResolvedValue({ success: true }),
};
const internalCommands = captureCommands();

await handler.execute(request);

expect(notifier.sync).toHaveBeenCalled();
expect(internalCommands).toContainEqual(
  expect.any(UpdateAccessCommand),
);
```

This can prove a local branch. It does not prove:

- the request passes real authentication and input validation;
- the route calls the correct application code;
- the real account query uses the correct key;
- the database update matches a record;
- the background work is registered and runs;
- the final access and notification state is correct.

Every one of those production failures can ship while this unit test stays green.

AI makes this problem larger. Agents are very good at copying visible structure. When a test mocks every collaborator and asserts the same internal calls, it shows the agent both the implementation and the expected answer. The agent can produce high coverage with little independent evidence.

The stronger loop is different:

1. Read the product requirement.
2. Seed the real preconditions.
3. Act through the real product boundary.
4. Assert the exact visible result.

## The default: one real action, all visible effects

Consider an endpoint that reactivates a withdrawn student:

```ts
await driver.request()
  .put(path)
  .set('Authorization', auth)
  .send({ notes })
  .expect(200);
```

One request can prove several related outcomes:

- the student status changed to active;
- an audit record stored the reason;
- analytics recorded the status change;
- no withdrawal document was sent to the student records system;
- no withdrawal notice was sent to the student.

The request crosses the real route, authentication, validation, business logic, and database. Email, analytics, queues, and document delivery are captured only at their external boundaries.

This gives the test the same perspective as the product requirement.

## When a unit test is the right choice

“Last resort” does not mean “never.” A lower-level test needs a concrete reason.

Good reasons include:

- **Pure logic:** a formula, parser, state machine, or date calculation with no collaborators.
- **Large input matrix:** hundreds of combinations where broad setup adds cost but no confidence.
- **Unreachable failure path:** an exact error that cannot be triggered honestly through a public boundary.
- **Negative asynchronous rule:** a side effect must not happen, but the system exposes no reliable completion signal.

Choose the lowest level that adds evidence, not the lowest level that is easy to mock.

## Tests as an agent contract

Behavior-level TDD creates a clear agreement between a person and a coding agent:

1. **Specify:** write the observable product behavior.
2. **Fail:** prove the test detects that the behavior is missing.
3. **Generate:** let the agent implement one increment.
4. **Verify:** run the real path and inspect the implementation.
5. **Keep:** retain the test as regression coverage.

The agent may change the implementation. It should not negotiate with the expected product outcome.

This also makes code review clearer. A reviewer can compare three things:

- the requested behavior;
- the changed tests;
- the changed implementation.

If the product behavior changed but no behavior test changed, the diff should raise a question. If only implementation details changed and many tests changed, the tests may be coupled at the wrong level.

## A real history: when tests should move

Two changes to the same learning journey—the student progress page—show the distinction.

### Internal optimization: zero test changes

A performance rewrite changed five production files:

```text
237 lines added
167 lines removed

repeated scans and sorts
        ↓
indexed lookups
```

Registration, lesson, course, ticket, and exam lookups moved from repeated scans to precomputed maps. Matching priority and stable tie-breaking stayed the same.

The integration spec remained byte-for-byte unchanged.

That is the ideal result of an internal optimization. The implementation changed substantially. The product contract did not move, so the tests did not move.

Repository commit: `e8f3b6d2`.

### Small product requirement: the test had to change

A later requirement changed how a historical failed attempt appeared. The old product hid a failed attempt after withdrawal. The new product kept it visible as history.

The test diff made the behavior change explicit:

```diff
- drops a failed withdrawn attempt
+ keeps a failed withdrawn attempt

- not.toContain(attemptId)
+ toContain(attemptId)

+ progressionEnded: true
```

The code change was smaller than the performance rewrite, but the product promise changed. The agent had to show that change in the test.

Repository commits: `912d3930` and `568bdf4c`.

The rule is:

> Implementation change: tests stay still. Product change: tests must move.

## Why integration tests become hard to read

The confidence of an integration test is broad, but its setup can be brutal:

- linked database records;
- IDs and relationships;
- dates and clocks;
- application wiring;
- cleanup;
- asynchronous effects.

All that plumbing can hide the one fact the test is meant to explain.

The solution is not to mock the plumbing away. The solution is to give the test a small domain language:

- builders create valid entities;
- drivers seed and operate the real system;
- local scenario seeders hide repeated invariants.

The test should expose the variation and hide the invariants.

## How to write a good test driver

A test driver is a thin domain language over real setup, a real action, and real outcomes.

```ts
const progress = await driver.given
  .student((student) =>
    student.withId(studentId))
  .given.course((course) =>
    course.withId(courseId).withLessons(4))
  .given.enrollment((enrollment) =>
    enrollment.withStudent(studentId))
  .when.getProgress(studentId);

const saved = await driver.then
  .storedProgress(studentId);
```

A good driver follows these rules:

### `given` records setup

Each `given` call configures one domain entity, stores it as pending setup, and returns the driver.

It does not write to the database immediately. It does not return the created entity. It is not asynchronous.

The spec creates important IDs before the chain and passes them into builders. This keeps relationships visible in the test:

```ts
const studentId = new ObjectId();
const courseId = new ObjectId();
```

### `when` performs one real action

The first `when` call writes all pending setup in the correct order, then performs the action through the real product boundary.

There should be one action under test. If a test needs several unrelated actions, it probably describes more than one behavior.

### `then` reads real outcomes

`then` reads persisted or externally visible outcomes after the action. It does not return values the driver already knew during setup.

### The spec owns correctness

The driver must not contain expected-value helpers or assertions. The spec decides what is correct.

```ts
const stored = await driver.then.storedProgress(studentId);

expect(stored.completedLessons).toEqual([lessonId]);
```

### One driver belongs to one feature spec

A spec driver should not become a general application SDK. If a second spec needs the same seeding mechanics, extract a shared base or module driver. Do not add unrelated actions to the first feature’s driver.

### Driver warning signs

Avoid:

- asynchronous `given` methods;
- returning seeded entities from `given`;
- hand-written database records;
- expected-value helpers;
- mocked internal services;
- fixed sleeps used as completion signals.

The spec owns meaning. The driver owns mechanics.

## How to write a good builder

A builder owns one valid entity. Tests state only the fields that matter.

```ts
new StudentBuilder()
  .withId(studentId)
  .withProgram('software-engineering')
  .withEnrollment((enrollment) =>
    enrollment
      .withCourse(courseId)
      .withStatus('active'))
  .build();
```

A good builder follows these rules:

### Start with valid, boring defaults

The default entity should satisfy fields that are required but irrelevant to most tests. A test should override only what matters to its behavior.

### Use setters for scalar fields

Use a predictable `withField(value)` shape:

```ts
builder
  .withId(studentId)
  .withName('Ada')
  .withStatus('active');
```

Add a setter only when a real test varies that field.

### Use builders for nested entities

Never pass a raw nested object when that entity has its own shape. Use a callback with its builder:

```ts
student.withEnrollment((enrollment) =>
  enrollment
    .withCourse(courseId)
    .withStatus('active'));
```

The parent owns the relationship. The nested builder owns the nested entity.

### Add convenience methods after repeated use

When the same meaningful state appears in more than one real test, add a convenience that composes the general builder:

```ts
withActiveEnrollment(courseId: ObjectId): this {
  return this.withEnrollment((enrollment) =>
    enrollment
      .withCourse(courseId)
      .withStatus('active'));
}
```

Do not add speculative setters or conveniences.

### Builder warning signs

Avoid:

- factories that take large options objects;
- raw database records in a spec;
- parallel builders for an entity that already has one;
- nested entities passed as plain objects;
- defaults whose values affect the behavior under test.

Never replace a builder with an options object or a hand-written database record.

## Local scenario seeders

Several tests may share the same multi-entity world. Repeating a long `given` chain in each test hides the one fact that varies.

A local scenario seeder composes that repeated setup:

```ts
studentEnrolledIn(studentId, courseId)
  .given.progress((progress) =>
    progress.withCompletedLessons(2));
```

The seeder keeps fixed invariants out of the test body. Everything still visible in the test should be load-bearing.

Keep a scenario seeder inside the spec until a second spec needs the same world.

## The hardest assertion: nothing happened

Suppose reactivating a withdrawn student must not send a withdrawal notice.

A tempting integration test is:

```ts
await driver.request()
  .put(reactivatePath(studentId))
  .set('Authorization', driver.auth(staffUser))
  .send({})
  .expect(200);

await sleep(200);

expect(notificationDriver.withdrawalNotices())
  .toHaveLength(0);
```

This does not prove that no notice will be sent. It proves only that no notice arrived within 200 milliseconds.

A slow worker can make a broken product look correct.

There are three honest options.

### Wait for a causal completion signal

Wait for an asynchronous event, acknowledgement, or persisted state that is guaranteed to occur after the notification decision:

```ts
await driver.waitForStatusChanged();

expect(driver.withdrawalNotices()).toEqual([]);
```

This preserves broad coverage. It also requires knowledge of critical ordering details, which makes it harder to design as pure black-box TDD.

### Expose workflow completion

If completion matters to the product or operations, expose it as durable state:

```ts
await driver.waitForWorkflowDone(runId);

expect(driver.withdrawalNotices()).toEqual([]);
```

An outbox status, task state, or test seam can make the whole workflow observable.

### Use a focused unit test

If no honest completion boundary exists, isolate the branching policy:

```ts
const commands = notificationPolicy.for(reversal);

expect(commands).not.toContainEmail();
```

Keep a positive integration test proving that the notification pipeline works at all.

“Not yet” is not the same as “will not.”

## Making broad tests fast

The obvious objection is speed.

A naïve integration suite repeats the expensive work for every spec file:

1. Build the application container.
2. Start the backend.
3. Register routes and request handlers.
4. Prepare and migrate the database.
5. Seed data.
6. Tear everything down.

The cost becomes:

```text
number of suites × (app boot + database setup + teardown)
```

Developers respond to a slow suite by skipping tests or replacing real handlers with mocks. The architecture of the test harness decides whether good tests are affordable.

## Boot the app once and isolate the data

Share expensive infrastructure across the test run:

- one real backend application;
- one real migrated database;
- one connection pool;
- controlled external seams.

Keep scenarios isolated through data ownership:

- generate fresh IDs;
- let each spec read only its own data;
- register cleanup before inserting;
- clean only records the spec owns;
- claim values that come from a small shared namespace.

Each spec then performs only the work unique to its scenario:

1. Seed its world.
2. Make a real request.
3. Assert real outcomes.
4. Clean what it owns.

This keeps integration tests broad without paying the full startup cost for every file.

## Operating rules

1. **Start at the real product entry point.** Use the HTTP API, command-line input, or client application.
2. **Keep internal collaborators real.** Seed the state their real code reads.
3. **Fake only true external delivery.** Capture the email, task, analytics event, or file.
4. **Assert exact observable outcomes.** Check state, events, return values, and side effects.
5. **Make asynchronous completion deterministic.** Never confuse a timeout with proof.
6. **Use unit tests with a concrete reason.** Pure logic, large matrices, unreachable paths, and honest negative checks are valid reasons.
7. **Keep setup readable.** Builders create valid entities, drivers operate the real system, and local seeders hide repeated invariants.
8. **Let tests move with the product.** Internal rewrites should not rewrite behavior tests. Product changes should.

Seed the real world. Run the real path. Give humans and agents a green worth trusting.

## Further reading

- [Kent C. Dodds: Write tests. Not too many. Mostly integration.](https://kentcdodds.com/blog/write-tests)
- [Martin Fowler: Test Pyramid](https://martinfowler.com/bliki/TestPyramid.html)
- [Google: Software Engineering at Google—Unit Testing](https://abseil.io/resources/swe-book/html/ch12.html)
- [Anthropic: Scaling Agentic Coding Across Your Organization](https://resources.anthropic.com/hubfs/Scaling%20agentic%20coding%20across%20your%20organization.pdf)

## Links

- [Presentation](https://oreliyahu.github.io/presentations/testing-in-the-ai-era/)
- [Markdown article](https://oreliyahu.github.io/presentations/testing-in-the-ai-era/article.md)
