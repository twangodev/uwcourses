<div align="center">
  <a href="https://uwcourses.com" target="_blank">
    <img alt="uwcourses" src="./static/uwcourses-logo.svg" width="64">
    <h1>uwcourses</h1>
  </a>
  <p>
    Check it out live at <a href="https://uwcourses.com/?utm_source=github.com">uwcourses.com</a>
  </p>
</div>

<p align="center">
  <a href="https://github.com/twangodev/uwcourses/actions/workflows/svelte.yml" target="_blank"><img alt="Svelte" src="https://github.com/twangodev/uwcourses/actions/workflows/svelte.yml/badge.svg"></a>
  <img alt="GitHub Release" src="https://img.shields.io/github/v/release/twangodev/uwcourses">
  <a href="https://www.gnu.org/licenses/agpl-3.0"><img alt="GitHub License" src="https://img.shields.io/github/license/twangodev/uwcourses"/></a>
  <img alt="Repository Size" src="https://img.shields.io/github/repo-size/twangodev/uwcourses"/>
  <a href="https://cheesehacks.webdevuw.com/" target="_blank"><img alt="Cheesehacks 2024" src="https://img.shields.io/badge/Cheesehacks-2024-fec732"/></a>
</p>

<p align="center">

</p>

## Problem Statement

The University of Wisconsin–Madison has 10,000+ courses spanning 190+ departments. With so many options, it can be challenging to navigate the course catalog and find the right courses for your academic goals. Students often struggle to understand the relationships between courses, leading to confusion and frustration when planning their schedules.

## Features

- **Course Requisite Graph**: Visualize the relationships between courses and their prerequisites using a graph.
- **Course Details**: View detailed information about each course, including prerequisites, co-requisites, and course descriptions.
- **Professor Ratings**: Quickly access ratings and reviews of professors for each course.
- **Course Search**: Search for courses by name, code, or subject.

## Development

```sh
bun install --frozen-lockfile
uv run --locked uwcourses-site import --limit 8
bun run dev
```

See the [local data pipeline](generation/README.md).

The current release shows official course learning outcomes. New inferred skills,
activities and activity filters remain disabled in `src/lib/course-learning-release.ts`
until their pilot meets the documented acceptance criteria. Existing course summaries
and search behavior remain available. Experimental component/query tests opt in
explicitly; production uses the release defaults.

See the [contributing guide](CONTRIBUTING.md) to help improve the project. The public API contract is generated at `/openapi.json`.

## Contributions

![Repobeats analytics visualization](https://repobeats.axiom.co/api/embed/6cef9c41661d58138630347f2b67a57c7872fe3a.svg "Repobeats analytics image")
