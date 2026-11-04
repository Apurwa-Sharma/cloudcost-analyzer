
# ------------------- Stage 1: Build Stage ------------------------------
FROM node:22-alpine AS frontend-builder

# Set the working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy the rest of the application code
COPY . .

# Build the React + Vite application
RUN npm run build


# ------------------- Stage 2: NGINX production server ------------------------------
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built frontend assets
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# Expose NGINX port
EXPOSE 80

# Start NGINX
CMD ["nginx", "-g", "daemon off;"]

