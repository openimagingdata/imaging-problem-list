# Flowbite Component Reference

This document provides examples and best practices for using Flowbite components in the Imaging Problem List viewer.

## CDN Setup (Version 4.0.0)

### Include in `<head>`:
```html
<link href="https://cdn.jsdelivr.net/npm/flowbite@4.0.0/dist/flowbite.min.css" rel="stylesheet" />
```

### Include before closing `</body>`:
```html
<script src="https://cdn.jsdelivr.net/npm/flowbite@4.0.0/dist/flowbite.min.js"></script>
```

## Dark Mode Setup

### Step 1: Enable Dark Mode in Tailwind Config
If using custom CSS, add to your input.css:
```css
@custom-variant dark (&:where(.dark, .dark *));
```

### Step 2: Initialize Theme on Page Load (in `<head>`)
```html
<script>
  if (localStorage.getItem('color-theme') === 'dark' ||
      (!('color-theme' in localStorage) &&
       window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
</script>
```

### Step 3: Theme Toggle Button
```html
<button id="theme-toggle" type="button"
  class="text-gray-500 dark:text-gray-400 hover:bg-gray-100
         dark:hover:bg-gray-700 focus:outline-none focus:ring-4
         focus:ring-gray-200 dark:focus:ring-gray-700 rounded-lg text-sm p-2.5">
  <svg id="theme-toggle-dark-icon" class="hidden w-5 h-5"
    fill="currentColor" viewBox="0 0 20 20">
    <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z"></path>
  </svg>
  <svg id="theme-toggle-light-icon" class="hidden w-5 h-5"
    fill="currentColor" viewBox="0 0 20 20">
    <path d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" fill-rule="evenodd" clip-rule="evenodd"></path>
  </svg>
</button>
```

### Step 4: Toggle Functionality Script
```javascript
var themeToggleDarkIcon = document.getElementById('theme-toggle-dark-icon');
var themeToggleLightIcon = document.getElementById('theme-toggle-light-icon');

// Initialize icons based on current theme
if (localStorage.getItem('color-theme') === 'dark' ||
    (!('color-theme' in localStorage) &&
     window.matchMedia('(prefers-color-scheme: dark)').matches)) {
  themeToggleLightIcon.classList.remove('hidden');
} else {
  themeToggleDarkIcon.classList.remove('hidden');
}

var themeToggleBtn = document.getElementById('theme-toggle');

themeToggleBtn.addEventListener('click', function() {
  // Toggle icon visibility
  themeToggleDarkIcon.classList.toggle('hidden');
  themeToggleLightIcon.classList.toggle('hidden');

  // Handle theme switching with localStorage
  if (localStorage.getItem('color-theme')) {
    if (localStorage.getItem('color-theme') === 'light') {
      document.documentElement.classList.add('dark');
      localStorage.setItem('color-theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('color-theme', 'light');
    }
  } else {
    if (document.documentElement.classList.contains('dark')) {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('color-theme', 'light');
    } else {
      document.documentElement.classList.add('dark');
      localStorage.setItem('color-theme', 'dark');
    }
  }
});
```

## Dropdown Component

### Basic Dropdown
```html
<!-- Trigger Button -->
<button id="dropdownButton" data-dropdown-toggle="dropdownMenu"
  class="text-gray-900 bg-white border border-gray-300 focus:outline-none
         hover:bg-gray-100 focus:ring-4 focus:ring-gray-100 font-medium
         rounded-lg text-sm px-5 py-2.5 dark:bg-gray-800 dark:text-white
         dark:border-gray-600 dark:hover:bg-gray-700 dark:hover:border-gray-600
         dark:focus:ring-gray-700"
  type="button">
  Dropdown button
  <svg class="w-2.5 h-2.5 ms-3" aria-hidden="true" fill="none" viewBox="0 0 10 6">
    <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"
          stroke-width="2" d="m1 1 4 4 4-4"/>
  </svg>
</button>

<!-- Dropdown Menu -->
<div id="dropdownMenu" class="z-10 hidden bg-white divide-y divide-gray-100
     rounded-lg shadow w-44 dark:bg-gray-700">
  <ul class="py-2 text-sm text-gray-700 dark:text-gray-200"
      aria-labelledby="dropdownButton">
    <li>
      <a href="#" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600
         dark:hover:text-white">Dashboard</a>
    </li>
    <li>
      <a href="#" class="block px-4 py-2 hover:bg-gray-100 dark:hover:bg-gray-600
         dark:hover:text-white">Settings</a>
    </li>
  </ul>
</div>
```

### Key Data Attributes
- `data-dropdown-toggle="dropdownId"` - Links trigger to menu by ID
- `data-dropdown-trigger="hover"` - Enable hover activation (default is click)
- `data-dropdown-placement="bottom"` - Position: top, right, bottom, left
- `data-dropdown-offset-distance="10"` - Distance from trigger

### Important Notes
- Flowbite's JavaScript automatically initializes dropdowns using data attributes
- No manual initialization required
- The menu must have `hidden` class initially

## Badge Component

### Status Badges (for our use case)

```html
<!-- Success/Present (Green) -->
<span class="bg-green-100 text-green-800 text-xs font-medium px-2.5 py-0.5
     rounded dark:bg-green-900 dark:text-green-300">
  Present
</span>

<!-- Warning/Resolved (Amber) -->
<span class="bg-yellow-100 text-yellow-800 text-xs font-medium px-2.5 py-0.5
     rounded dark:bg-yellow-900 dark:text-yellow-300">
  Resolved
</span>

<!-- Gray/Not Present -->
<span class="bg-gray-100 text-gray-800 text-xs font-medium px-2.5 py-0.5
     rounded dark:bg-gray-700 dark:text-gray-300">
  Not Present
</span>

<!-- Info/Blue -->
<span class="bg-blue-100 text-blue-800 text-xs font-medium px-2.5 py-0.5
     rounded dark:bg-blue-900 dark:text-blue-300">
  Ever Present
</span>
```

### Pill Badges (Rounded)
Add `rounded-full` instead of `rounded`:
```html
<span class="bg-green-100 text-green-800 text-xs font-medium px-2.5 py-0.5
     rounded-full dark:bg-green-900 dark:text-green-300">
  Present
</span>
```

## Card Component

### Basic Card with Dark Mode
```html
<div class="max-w-sm p-6 bg-white border border-gray-200 rounded-lg shadow
     dark:bg-gray-800 dark:border-gray-700">
  <h5 class="mb-2 text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
    Card Title
  </h5>
  <p class="mb-3 font-normal text-gray-700 dark:text-gray-400">
    Card content goes here.
  </p>
</div>
```

### Interactive Card with Hover
```html
<div class="max-w-sm p-6 bg-white border border-gray-200 rounded-lg shadow
     hover:bg-gray-100 dark:bg-gray-800 dark:border-gray-700
     dark:hover:bg-gray-700 cursor-pointer">
  <!-- Card content -->
</div>
```

### Card with Button
```html
<div class="max-w-sm p-6 bg-white border border-gray-200 rounded-lg shadow
     dark:bg-gray-800 dark:border-gray-700">
  <h5 class="mb-2 text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
    Finding Name
  </h5>
  <p class="mb-3 font-normal text-gray-700 dark:text-gray-400">
    Finding description
  </p>
  <a href="#" class="inline-flex items-center px-3 py-2 text-sm font-medium
     text-center text-white bg-blue-700 rounded-lg hover:bg-blue-800
     focus:ring-4 focus:outline-none focus:ring-blue-300
     dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-800">
    View Details
    <svg class="rtl:rotate-180 w-3.5 h-3.5 ms-2" aria-hidden="true"
         fill="none" viewBox="0 0 14 10">
      <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"
            stroke-width="2" d="M1 5h12m0 0L9 1m4 4L9 9"/>
    </svg>
  </a>
</div>
```

## Button Component

### Primary Button
```html
<button type="button" class="text-white bg-blue-700 hover:bg-blue-800
        focus:ring-4 focus:ring-blue-300 font-medium rounded-lg text-sm
        px-5 py-2.5 dark:bg-blue-600 dark:hover:bg-blue-700
        focus:outline-none dark:focus:ring-blue-800">
  Primary
</button>
```

### Secondary Button
```html
<button type="button" class="text-gray-900 bg-white border border-gray-300
        focus:outline-none hover:bg-gray-100 focus:ring-4 focus:ring-gray-100
        font-medium rounded-lg text-sm px-5 py-2.5 dark:bg-gray-800
        dark:text-white dark:border-gray-600 dark:hover:bg-gray-700
        dark:hover:border-gray-600 dark:focus:ring-gray-700">
  Secondary
</button>
```

### Filter Button (Toggle State)
```html
<button type="button" class="px-3 py-2 text-xs font-medium text-center
        text-white bg-blue-700 rounded-lg hover:bg-blue-800 focus:ring-4
        focus:outline-none focus:ring-blue-300 dark:bg-blue-600
        dark:hover:bg-blue-700 dark:focus:ring-blue-800">
  Active Filter
</button>

<button type="button" class="px-3 py-2 text-xs font-medium text-gray-900
        focus:outline-none bg-white rounded-lg border border-gray-200
        hover:bg-gray-100 hover:text-blue-700 focus:z-10 focus:ring-4
        focus:ring-gray-100 dark:focus:ring-gray-700 dark:bg-gray-800
        dark:text-gray-400 dark:border-gray-600 dark:hover:text-white
        dark:hover:bg-gray-700">
  Inactive Filter
</button>
```

## Form Elements

### Select Dropdown
```html
<select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm
       rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5
       dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400
       dark:text-white dark:focus:ring-blue-500 dark:focus:border-blue-500">
  <option selected>Choose an option</option>
  <option value="1">Option 1</option>
  <option value="2">Option 2</option>
</select>
```

## Best Practices for Dark Mode

1. **Always include both light and dark variants** for all colored elements
2. **Use semantic color classes**:
   - Text: `text-gray-900 dark:text-white`
   - Backgrounds: `bg-white dark:bg-gray-800`
   - Borders: `border-gray-200 dark:border-gray-700`
3. **Test both themes** to ensure readability and contrast
4. **Use Flowbite's color system** instead of arbitrary values for consistency
5. **Initialize theme before page render** to prevent flash of unstyled content

## Common Dark Mode Color Pairings

| Element | Light Mode | Dark Mode |
|---------|-----------|-----------|
| Page background | `bg-gray-50` | `dark:bg-gray-900` |
| Card background | `bg-white` | `dark:bg-gray-800` |
| Card border | `border-gray-200` | `dark:border-gray-700` |
| Primary text | `text-gray-900` | `dark:text-white` |
| Secondary text | `text-gray-700` | `dark:text-gray-300` |
| Muted text | `text-gray-500` | `dark:text-gray-400` |
| Hover background | `hover:bg-gray-100` | `dark:hover:bg-gray-700` |

## References

- [Flowbite Official Documentation](https://flowbite.com/docs/)
- [Flowbite Dark Mode Guide](https://flowbite.com/docs/customize/dark-mode/)
- [Flowbite Components](https://flowbite.com/docs/components/)
