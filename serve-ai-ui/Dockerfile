FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package.json yarn.lock* ./

# Install dependencies
RUN yarn install --frozen-lockfile || yarn install

# Copy application code
COPY . .

# Build arg — must be passed at build time so React can bake it into the bundle
ARG REACT_APP_BACKEND_URL
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL

# Build for production
RUN yarn build

# Install serve for static file serving
RUN yarn global add serve

# Expose port
EXPOSE 3000

# Serve the build
CMD ["serve", "-s", "build", "-l", "3000"]
