# Halcyon

## Intro

First of all I wanted to say this was a great task! Really enjoyed building this out and great that it is able to cover more than the usual code only challenge.

I've kept the info below mostly focused on decisions I made and explanations I think will be important, rather than filling space with a quick start or list of packages & commands (that can be found in `package.json`).

This project was completed over two separate roughly two hour sessions.

## Public Sites

There are public staging & production versions of the apps.

**Staging**

- Mock Data API/MCP - https://staging-mock.joinhalcyon.app
- Agent API - https://staging-api.joinhalcyon.app
- Test UI - https://staging-app.joinhalcyon.app

**Production**

- Mock Data API/MCP - https://mock.joinhalcyon.app
- Agent API - https://api.joinhalcyon.app
- Test UI - https://app.joinhalcyon.app

(https://app.joinhalcyon.app/?dev=1 if you want to get some dev tools used for testing. This adds a side panel with response times, the tool calls the agent made and the user's saved memories, as well as settings for changing the user, conversation and streaming)

## Core Decisions

I decided to keep the AI API and mock data separated to mimic a slightly more realistic set up with distinct apps and MCP/API connections between the agent API and the mock 3rd party services.

To keep the surface of this lower (as it's a demo application) I merged the 3rd party mock applications into a single app with a single shared database for persistence.

The two services I landed on were a calendar integration and a restaurant lookup and booking service. These felt like the minimum required to be able to serve the requirement of booking tables for users without needing too many questions about location or availability.

I also decided that I wanted to include an option for text streaming in the AI chat, as this application is for discerning users and the feel of the chat being responsive and realtime would be important for the UX of a product like this.

I however still needed to support the contract and so I added a non-default option to allow response streaming (`?stream=true` on the message endpoint), and then added a UI component to the repo that supported streaming both as an extra bonus in the task but also as a way for quicker more manual testing of the LLM.

For hosting I landed on Cloudflare for hosting and IaC as it's lightweight, quick to set up, and supported all the hosting requirements I would need for a mock application (static file hosting, containers, databases). I also quite liked the idea of having an actual domain for this task, and while probably not necessary Cloudflare domains are sold at cost so it was the cheapest option!

## Repo Structure

This project is a monorepo containing 3 apps. The core app is the agent API and uses Python (with FastAPI and Uvicorn).

The mock data API is also Python and has a REST API for the calendar service (softly mimicking the data that Google Calendar or similar would expose), and an MCP server for restaurant discovery and booking.

The test UI is a small React app used for chatting with the agent.

There is also a `scripts` folder for the setup, local dev and deployment commands, and a `dev/d1-local` app which is a local version of the Cloudflare database so everything can be run locally.

## The Agent

The agent saves memories about users as it goes (dietary needs, home city, who they dine with, budget etc.) and these are given back to it at the start of every message. I pushed the agent to collect these without being asked, as the more it knows about a user the fewer questions it needs to ask next time.

The member's five most recent earlier conversations (oldest first, dated, without the status lines) are also given to the agent, so requests like "the same again" resolve against what was actually discussed rather than only against the last booking.

Each turn uses two models for speed. A fast tool model (Haiku 5.5) runs the tool calls (diary, searches, memory, bookings) and calls a `ready_to_reply` signal once it has what it needs; the reply model (Sonnet 5.5) then writes the member-facing reply. Set `TOOL_MODEL=` (empty) to use one model for everything.

Restaurant listings carry dietary options, an `allergen_safe` list (allergens the kitchen says it can reliably keep out, e.g. gluten for coeliacs), allergen notes and a spice level. One search can filter on all of these, include neighbouring areas, exclude venues, and return only places with a table.

Restaurants are only available in 4 cities (London, Paris, New York and Los Angeles). The agent works out which city the user will be in from what they say, then their calendar, then their home city, and only asks if it still doesn't know.

If the agent hasn't sent a message after 9 seconds (usually when it's working through a few tool calls) it sends a short holding message, so the user is never waiting more than 12 seconds. The 12 second limit was chosen to avoid situations where the test process (which responds 15 seconds after the final AI message) causes issues.

When a table is booked the agent also adds it to the user's calendar, and it can change or cancel bookings (and the calendar entries) if the user's plans change.

## Mock Data

The restaurant data is static JSON data saved in the mock-services app. This is then served via MCP to the AI agent. Mock bookings and availability is also generated, then augmented by bookings actually made and stored in the mock data database.

The calendar data is generated on the fly from a set of AI written seed data. This was the quickest way to get a unique set of data initialised for each user, without knowing which users exist or when they would be using the service. Calendar data is also augmented by the calendar events the agent adds when tables are booked.

## Deployment

Deployment is handled through a `package.json` command in the root of the repo. This is split into staging & production with all 3 apps being deployed via Wrangler.

## Known Faults

Due to this not being a real application or infrastructure there are some known faults and flaws.

- Keys are added to built frontend files during deployment. This was left for simplicity when deploying. If the application was to be made real the test UI would need user authentication and a backend that could act as a proxy to the agent API.
- Calendar mock data is randomly generated. This data may not line up with the test user's data which could cause confusing conflicts.
- Initialising the calendar for a user writes in bulk to the database, which on this low end infrastructure causes a slight delay during the first message a new user has where a calendar look up is required.
- The agent API can only run as a single instance, as messages are handled in memory. To scale this the conversation state would need to move somewhere shared.
- The deployment process is fairly rough and has hardcoded sites for staging and production. In a real application I would make this more dynamic and robust (and not built and deployed from a local machine!)
- Stored memory as an approach lead to a lack of continunity between chats, especially when a user referenced a specific previous chat. To overcome this previous chats are loaded into context (which is a suitable solution for a short set of conversations similar to what the tests have). This would not be suitable for a long term use application, and so a combination of async chat summary (summarising chats in the background to keep a general idea of what's been discussed into the future) and providing only full chat transcripts for the previous 3-5 chats would be required.