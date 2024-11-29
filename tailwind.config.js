/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    'client/templates/client/*.html',
    'core/templates/core/*.html',
    'core/templates/core/partials/*.html',
    'dashboard/templates/dashboard/*.html',
    'lead/templates/lead/*.html',
    'team/templates/team/*.html',
    'userprofile/templates/userprofile/*.html',
    'actions/templates/actions/*.html',  // Make sure this is included if applicable
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}

